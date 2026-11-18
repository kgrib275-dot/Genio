"""운영 준비 1차 A3: 외부 백업(바깥 S3 호환 저장소)과 복구 연습 상태."""

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from api.config import get_settings
from api.services import offsite_backup
from api.services import status as status_service


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, datetime] = {}
        self.uploads: list[str] = []
        self.fail = False

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.objects:
            err = Exception("missing")
            err.response = {"Error": {"Code": "404"}}  # type: ignore[attr-defined]
            raise err
        return {}

    def upload_file(self, path: str, bucket: str, key: str) -> None:
        if self.fail:
            raise ConnectionError("down")
        assert os.path.exists(path)
        self.uploads.append(key)
        self.objects[key] = datetime.now(UTC)

    def list_objects_v2(self, **kw: Any) -> dict[str, Any]:
        return {
            "Contents": [
                {"Key": k, "LastModified": t}
                for k, t in self.objects.items()
                if k.startswith(kw["Prefix"])
            ],
            "IsTruncated": False,
        }

    def delete_object(self, Bucket: str, Key: str) -> None:  # noqa: N803
        self.objects.pop(Key, None)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def set(self, k: str, v: str, ex: int | None = None) -> None:
        self.data[k] = v.encode()

    def get(self, k: str) -> bytes | None:
        return self.data.get(k)


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[FakeS3, Path]:
    st = get_settings()
    monkeypatch.setattr(st, "genio_backup_dir", str(tmp_path))
    monkeypatch.setattr(st, "genio_backup_s3_bucket", "offsite")
    monkeypatch.setattr(st, "genio_backup_s3_prefix", "genio-backups")
    monkeypatch.setattr(st, "genio_backup_s3_keep_days", 30)
    r = FakeRedis()
    from api.engine import events

    monkeypatch.setattr(events, "_client", lambda: r)
    return FakeS3(), tmp_path


def _dump(folder: Path, name: str, days_ago: float = 0) -> Path:
    p = folder / name
    p.write_bytes(b"PGDMP fake")
    t = time.time() - days_ago * 86400
    os.utime(p, (t, t))
    return p


def test_off_without_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "genio_backup_s3_bucket", "")
    assert offsite_backup.sync() == {"status": "off"}
    item = status_service._offsite()
    assert item["status"] == "warn" and "이 PC에만" in item["detail"]


def test_uploads_recent_once_and_prunes_old(setup: tuple[FakeS3, Path]) -> None:
    s3, folder = setup
    _dump(folder, "genio-20261117-0300.dump", days_ago=1)
    _dump(folder, "genio-20261118-0300.dump", days_ago=0)
    _dump(folder, "genio-20261101-0300.dump", days_ago=17)  # 오래된 로컬은 올리지 않는다
    (folder / "before-restore-1.dump").write_bytes(b"x")  # 다른 이름은 무시
    s3.objects["genio-backups/genio-20260901-0300.dump"] = datetime.now(UTC) - timedelta(days=60)
    s3.objects["genio-backups/notes.txt"] = datetime.now(UTC) - timedelta(days=60)
    out = offsite_backup.sync(client=s3)
    assert out["status"] == "ok"
    assert sorted(out["uploaded"]) == ["genio-20261117-0300.dump", "genio-20261118-0300.dump"]
    assert out["deleted"] == 1 and "genio-backups/notes.txt" in s3.objects
    # 다시 돌리면 이미 올린 것은 건너뛴다
    again = offsite_backup.sync(client=s3)
    assert again["uploaded"] == [] and len(s3.uploads) == 2
    item = status_service._offsite()
    assert item["status"] == "ok" and "genio-20261118-0300.dump" in item["detail"]


def test_failure_recorded(setup: tuple[FakeS3, Path]) -> None:
    s3, folder = setup
    _dump(folder, "genio-20261118-0300.dump")
    s3.fail = True
    out = offsite_backup.sync(client=s3)
    assert out["status"] == "error" and "올리지 못했어요" in out["message"]
    assert status_service._offsite()["status"] == "error"


def test_verify_status(setup: tuple[FakeS3, Path]) -> None:
    _, folder = setup
    now = datetime.now(UTC)
    assert status_service._verify(now)["status"] == "unknown"
    rec = {
        "status": "ok",
        "file": "genio-20261118-0300.dump",
        "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seconds": 3,
        "tables": 42,
        "rows": {"users": 5},
        "message": "",
    }
    (folder / "verify.json").write_text(json.dumps(rec), encoding="utf-8")
    item = status_service._verify(now)
    assert item["status"] == "ok" and "표 42개" in item["detail"]
    assert status_service._verify(now + timedelta(days=9))["status"] == "warn"
    (folder / "verify.json").write_text(
        json.dumps({**rec, "status": "error", "message": "복구 실패: x"}), encoding="utf-8"
    )
    assert status_service._verify(now)["status"] == "error"


def test_offsite_task_uses_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    from worker import tasks

    monkeypatch.setattr(get_settings(), "genio_backup_s3_bucket", "")
    assert tasks.offsite_backup_task.run() == {"status": "off"}
    monkeypatch.setattr(get_settings(), "genio_backup_s3_bucket", "b")
    seen: list[str] = []
    monkeypatch.setattr(
        tasks, "run_once", lambda name, period, fn, lock_seconds=600: seen.append(name) or {}
    )
    tasks.offsite_backup_task.run()
    assert seen == ["offsite_backup"]


def test_verify_script_present_and_mounted() -> None:
    root = Path(__file__).resolve().parents[3]
    script = (root / "scripts" / "verify_backup.sh").read_text(encoding="utf-8")
    assert "genio_verify" in script and "DROP DATABASE IF EXISTS" in script
    assert "verify_backup.sh" in (root / "docker-compose.yml").read_text(encoding="utf-8")
    loop = (root / "scripts" / "backup_loop.sh").read_text(encoding="utf-8")
    assert "verify_backup.sh" in loop
