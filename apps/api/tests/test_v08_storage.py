"""v0.8 파일 저장소(db·disk·s3): 기본 동작 그대로, 경로 탈출 거절, 가짜 S3, 옮기기 도구."""
# ruff: noqa: N803

import importlib.util
import io
import json
import struct
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.config import get_settings
from api.db import SessionLocal
from api.engine.executor import RunServices
from api.models import Document, StoredFile
from api.services import storage, storage_migrate
from api.services.storage import DiskBackend, S3Backend, StorageError, validate_key
from api.tests.conftest import Team, add_llm
from api.tests.fakes import FakeAdapter
from nodes import NodeError


# ---------------- 도구 ----------------
@pytest.fixture(autouse=True)
def _reset_backends() -> Iterator[None]:
    storage.set_backend(storage.DISK, None)
    storage.set_backend(storage.S3, None)
    yield
    for name in (storage.DISK, storage.S3):
        storage.set_backend(name, None)


@pytest.fixture
def disk_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    st = get_settings()
    monkeypatch.setattr(st, "genio_storage", "disk")
    monkeypatch.setattr(st, "genio_storage_dir", str(tmp_path / "files"))
    storage._build.cache_clear()
    yield_path = tmp_path / "files"
    return yield_path


class FakeClientError(Exception):
    def __init__(self, code: str, status: int) -> None:
        super().__init__(f"{code} secret-endpoint.example.com key=AKIASECRET")
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}


class FakeS3:
    """boto3 S3 클라이언트 흉내(메모리). 네트워크를 쓰지 않는다."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str | None]] = {}
        self.down = False

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str | None = None
    ) -> None:
        if self.down:
            raise ConnectionError("endpoint https://secret-endpoint.example.com unreachable")
        self.objects[(Bucket, Key)] = (bytes(Body), ContentType)

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if self.down:
            raise ConnectionError("endpoint https://secret-endpoint.example.com unreachable")
        if (Bucket, Key) not in self.objects:
            raise FakeClientError("NoSuchKey", 404)
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)][0])}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if (Bucket, Key) not in self.objects:
            raise FakeClientError("404", 404)
        return {"ContentLength": len(self.objects[(Bucket, Key)][0])}

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.objects.pop((Bucket, Key), None)

    def get_paginator(self, name: str) -> "FakeS3":
        assert name == "list_objects_v2"
        return self

    def paginate(self, *, Bucket: str, Prefix: str) -> Iterator[dict[str, Any]]:
        keys = sorted(k for (b, k) in self.objects if b == Bucket and k.startswith(Prefix))
        yield {"Contents": [{"Key": k} for k in keys]}


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 4 for _ in range(4))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _upload(client: TestClient, team: Team, name: str, data: bytes, mime: str) -> dict[str, Any]:
    r = client.post(
        f"/api/v1/workspaces/{team.ws}/files",
        files={"file": (name, io.BytesIO(data), mime)},
        headers=team.h("builder"),
    )
    assert r.status_code in (200, 201), r.text
    out: dict[str, Any] = r.json()
    return out


# ---------------- 키 검사·디스크 ----------------
@pytest.mark.parametrize(
    "bad",
    [
        "",
        "../x",
        "/abs/x",
        "a/../b",
        "a//b",
        "a\\b",
        ".hidden/x",
        "a/./b",
        "x\x00y",
        "a/" + "b" * 300,
    ],
)
def test_validate_key_rejects_traversal(bad: str) -> None:
    with pytest.raises(StorageError):
        validate_key(bad)


def test_validate_key_accepts_generated_keys() -> None:
    assert validate_key(storage.new_key("files")).startswith("files/")


def test_disk_backend_roundtrip_and_traversal(tmp_path: Path) -> None:
    be = DiskBackend(tmp_path / "root")
    be.put("files/abc", b"hello", "text/plain")
    assert be.get("files/abc") == b"hello" and be.exists("files/abc") and be.size("files/abc") == 5
    assert list(be.iter_keys("files/")) == ["files/abc"]
    for bad in ("../evil", "/etc/passwd", "files/../../evil", "..\\evil"):
        for op in (lambda k: be.put(k, b"x"), be.get, be.delete, be.exists):
            with pytest.raises(StorageError):
                op(bad)
    assert not (tmp_path / "evil").exists()
    be.delete("files/abc")
    assert not be.exists("files/abc")
    be.delete("files/abc")  # 두 번 지워도 오류 없음
    with pytest.raises(StorageError) as exc:
        be.get("files/abc")
    assert exc.value.status == 404 and exc.value.hint


def test_disk_backend_symlink_escape_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"top secret")
    root = tmp_path / "root"
    root.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("이 환경에서는 심볼릭 링크를 만들 수 없어요")
    with pytest.raises(StorageError):
        DiskBackend(root).get("link/secret.txt")


# ---------------- 가짜 S3 ----------------
def test_s3_backend_roundtrip_and_prefix() -> None:
    fake = FakeS3()
    be = S3Backend(fake, "bkt", "genio/")
    be.put("files/a1", b"data", "image/png")
    assert ("bkt", "genio/files/a1") in fake.objects
    assert fake.objects[("bkt", "genio/files/a1")][1] == "image/png"
    assert be.get("files/a1") == b"data" and be.size("files/a1") == 4 and be.exists("files/a1")
    assert not be.exists("files/none")
    assert list(be.iter_keys("files/")) == ["files/a1"]
    be.delete("files/a1")
    assert not be.exists("files/a1")
    with pytest.raises(StorageError) as exc:
        be.get("files/a1")
    assert exc.value.status == 404
    with pytest.raises(StorageError):
        be.put("../escape", b"x")


def test_s3_errors_hide_endpoint_and_keys() -> None:
    fake = FakeS3()
    fake.down = True
    be = S3Backend(fake, "bkt")
    with pytest.raises(StorageError) as exc:
        be.put("files/a", b"x")
    text = f"{exc.value.message} {exc.value.hint}"
    assert "S3" in text and exc.value.hint
    assert "secret-endpoint" not in text and "AKIA" not in text


def test_make_s3_client_requires_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    st = get_settings()
    monkeypatch.setattr(st, "genio_s3_bucket", "")
    with pytest.raises(StorageError) as exc:
        storage.make_s3_client(st)
    assert "GENIO_S3_BUCKET" in exc.value.hint


def test_make_s3_client_builds_real_boto3_client(monkeypatch: pytest.MonkeyPatch) -> None:
    st = get_settings()
    monkeypatch.setattr(st, "genio_s3_bucket", "bkt")
    monkeypatch.setattr(st, "genio_s3_endpoint_url", "http://minio.local:9000")
    monkeypatch.setattr(st, "genio_s3_access_key", "ak")
    monkeypatch.setattr(st, "genio_s3_secret_key", "sk")
    monkeypatch.setattr(st, "genio_s3_path_style", True)
    client = storage.make_s3_client(st)  # 연결은 만들지 않고 클라이언트만 만든다
    assert client.meta.endpoint_url == "http://minio.local:9000"


# ---------------- 기본(db) 그대로 ----------------
def test_default_db_backend_is_unchanged(client: TestClient, team: Team) -> None:
    assert storage.configured_name() == "db" and storage.configured_backend() is None
    data = _png()
    up = _upload(client, team, "a.png", data, "image/png")
    with SessionLocal() as db:
        f = db.get(StoredFile, up["id"])
        assert f is not None
        assert f.storage == "db" and f.storage_key is None and f.content == data
        assert storage.read_content(f) == data
        assert RunServices(db, team.ws).read_file(file_id=f.id)[2] == data


# ---------------- 디스크로 쓰기·읽기 ----------------
def test_upload_to_disk_and_read_back(client: TestClient, team: Team, disk_mode: Path) -> None:
    data = _png()
    up = _upload(client, team, "b.png", data, "image/png")
    with SessionLocal() as db:
        f = db.get(StoredFile, up["id"])
        assert f is not None
        assert f.storage == "disk" and f.content == b"" and f.size == len(data)
        assert f.storage_key and f.storage_key.startswith("files/")
        assert (disk_mode / f.storage_key).read_bytes() == data
        # 엔진(파일 입력)과 읽기 도우미 모두 저장소에서 읽는다
        assert RunServices(db, team.ws).read_file(file_id=f.id) == ("b.png", "image/png", data)
        # 다른 워크스페이스의 파일은 안 보인다
        with pytest.raises(NodeError):
            RunServices(db, "other-ws").read_file(file_id=f.id)


def test_missing_stored_file_gives_two_line_error(
    client: TestClient, team: Team, disk_mode: Path
) -> None:
    up = _upload(client, team, "c.txt", b"hello world", "text/plain")
    with SessionLocal() as db:
        f = db.get(StoredFile, up["id"])
        assert f is not None and f.storage_key
        (disk_mode / f.storage_key).unlink()
        with pytest.raises(NodeError) as exc:
            RunServices(db, team.ws).read_file(file_id=f.id)
        assert "찾지 못했어요" in str(exc.value)


def test_share_image_served_from_storage(client: TestClient, team: Team, disk_mode: Path) -> None:
    from api.tests.test_v08_share_meta import _deploy

    _app, dep_id, token = _deploy(client, team)
    up = _upload(client, team, "thumb.png", _png(), "image/png")
    r = client.patch(
        f"/api/v1/deployments/{dep_id}",
        json={"appearance": {"share_image": up["id"]}},
        headers=team.h("builder"),
    )
    assert r.status_code == 200, r.text
    img = client.get(f"/api/v1/public/apps/{token}/share-image")
    assert img.status_code == 200 and img.content == _png()
    # 저장소에서 사라지면 기본 그림으로 돌아간다(500이 아니다)
    for p in disk_mode.rglob("*"):
        if p.is_file():
            p.unlink()
    again = client.get(f"/api/v1/public/apps/{token}/share-image")
    assert again.status_code == 200 and again.content != _png()


def test_mixed_backends_old_files_still_readable(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """db에 올린 파일은 저장소를 disk로 바꾼 뒤에도 그대로 읽힌다."""
    old = _upload(client, team, "old.txt", b"old bytes", "text/plain")
    st = get_settings()
    monkeypatch.setattr(st, "genio_storage", "disk")
    monkeypatch.setattr(st, "genio_storage_dir", str(tmp_path / "f"))
    storage._build.cache_clear()
    new = _upload(client, team, "new.txt", b"new bytes", "text/plain")
    with SessionLocal() as db:
        a, b = db.get(StoredFile, old["id"]), db.get(StoredFile, new["id"])
        assert a is not None and b is not None
        assert (a.storage, b.storage) == ("db", "disk")
        assert (storage.read_content(a), storage.read_content(b)) == (b"old bytes", b"new bytes")


# ---------------- 지식 문서 ----------------
def test_knowledge_documents_use_storage(
    client: TestClient, team: Team, fake_llm: FakeAdapter, disk_mode: Path
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": "규정"},
        headers=team.h("builder"),
    ).json()
    res = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={
            "file": ("규정.txt", "연차는 15일이에요. 주차는 B2층이에요.".encode(), "text/plain")
        },
        headers=team.h("builder"),
    )
    assert res.status_code == 200, res.text
    doc = res.json()
    assert doc["status"] == "ready"  # 저장소에서 읽어서 처리까지 끝났다
    with SessionLocal() as db:
        d = db.get(Document, doc["id"])
        assert d is not None and d.storage == "disk" and d.content is None and d.storage_key
        path = disk_mode / d.storage_key
        assert path.read_bytes().startswith("연차".encode())
        key = d.storage_key
    # 문서를 지우면 저장소의 본문도 지워진다
    assert (
        client.delete(f"/api/v1/documents/{doc['id']}", headers=team.h("builder")).status_code
        == 204
    )
    assert not (disk_mode / key).exists()
    # 지식베이스를 지울 때도 문서 본문이 정리된다
    r2 = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={
            "file": ("b.txt", "두 번째 문서 내용이에요 충분히 길게 적어요.".encode(), "text/plain")
        },
        headers=team.h("builder"),
    ).json()
    with SessionLocal() as db:
        d2 = db.get(Document, r2["id"])
        assert d2 is not None and d2.storage_key
        key2 = d2.storage_key
    assert (
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=team.h("builder")).status_code
        == 204
    )
    assert not (disk_mode / key2).exists()


# ---------------- 옮기기 도구 ----------------
def _seed_db_files(client: TestClient, team: Team) -> list[str]:
    ids = []
    for i in range(3):
        ids.append(
            _upload(client, team, f"f{i}.txt", f"본문 {i} ".encode() * 20, "text/plain")["id"]
        )
    return ids


def test_migrate_dry_run_changes_nothing(client: TestClient, team: Team, tmp_path: Path) -> None:
    _seed_db_files(client, team)
    storage.set_backend(storage.DISK, DiskBackend(tmp_path / "m"))
    with SessionLocal() as db:
        rep = storage_migrate.migrate_to_storage(db, "disk", dry_run=True)
        assert rep.moved == 3 and rep.failed == 0 and rep.bytes_moved > 0
        rows = list(db.scalars(select(StoredFile)))
        assert all(r.storage == "db" and r.content for r in rows)
    assert not (tmp_path / "m").exists() or not any((tmp_path / "m").rglob("*"))


def test_migrate_keeps_db_bytes_then_clear_then_restore(
    client: TestClient, team: Team, tmp_path: Path
) -> None:
    ids = _seed_db_files(client, team)
    storage.set_backend(storage.DISK, DiskBackend(tmp_path / "m"))
    with SessionLocal() as db:
        before = {i: bytes(db.get(StoredFile, i).content) for i in ids}  # type: ignore[union-attr]
        rep = storage_migrate.migrate_to_storage(db, "disk", models=["files"], batch=2)
        assert rep.moved == 3 and rep.cleared == 0
        for i in ids:
            f = db.get(StoredFile, i)
            assert (
                f is not None and f.storage == "disk" and f.content == before[i]
            )  # DB 본문은 그대로
            assert storage.read_content(f) == before[i]
        # 이어서 다시 돌리면 할 일이 없다(재개 가능)
        again = storage_migrate.migrate_to_storage(db, "disk", models=["files"])
        assert again.moved == 0
        assert storage_migrate.count_pending(db, ["files"]) == 0
        # DB 본문 비우기는 따로 요청해야 한다: 새 파일 하나를 db로 올려서 --clear-db 시험
    up = _upload(client, team, "late.txt", "늦게 온 파일 ".encode() * 10, "text/plain")
    with SessionLocal() as db:
        late = db.get(StoredFile, up["id"])
        assert late is not None and late.storage == "db"
        rep2 = storage_migrate.migrate_to_storage(db, "disk", models=["files"], clear_db=True)
        assert rep2.moved == 1 and rep2.cleared == 1
        db.refresh(late)
        assert late.content == b"" and late.storage == "disk"
        assert storage.read_content(late).startswith("늦게".encode())
        # 되돌리기: 저장소의 본문을 DB로
        back = storage_migrate.restore_to_db(db, models=["files"])
        assert back.moved == 4 and back.failed == 0
        for i in [*ids, up["id"]]:
            f = db.get(StoredFile, i)
            assert f is not None and f.storage == "db" and f.storage_key is None and f.content


def test_migrate_verifies_before_switching(client: TestClient, team: Team, tmp_path: Path) -> None:
    """저장소에서 다시 읽은 내용이 원본과 다르면 행을 바꾸지 않는다."""
    ids = _seed_db_files(client, team)

    class Corrupting(DiskBackend):
        def get(self, key: str) -> bytes:
            return super().get(key)[:-1]  # 한 바이트 모자라게 돌려준다

    storage.set_backend(storage.DISK, Corrupting(tmp_path / "m"))
    with SessionLocal() as db:
        rep = storage_migrate.migrate_to_storage(db, "disk", models=["files"], clear_db=True)
        assert rep.failed == 3 and rep.moved == 0 and rep.cleared == 0
        for i in ids:
            f = db.get(StoredFile, i)
            assert f is not None and f.storage == "db" and f.content  # 그대로
    # 실패한 쓰기는 저장소에서도 지운다(고아 파일 없음)
    assert not any(p.is_file() for p in (tmp_path / "m").rglob("*"))


def test_migrate_documents_and_orphans(
    client: TestClient, team: Team, fake_llm: FakeAdapter, tmp_path: Path
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": "k"},
        headers=team.h("builder"),
    ).json()
    client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={
            "file": ("a.txt", "문서 본문이 충분히 길어야 처리돼요. ".encode() * 5, "text/plain")
        },
        headers=team.h("builder"),
    )
    be = DiskBackend(tmp_path / "m")
    storage.set_backend(storage.DISK, be)
    with SessionLocal() as db:
        rep = storage_migrate.migrate_to_storage(db, "disk", models=["documents"], clear_db=True)
        assert rep.moved == 1 and rep.cleared == 1
        doc = db.scalar(select(Document))
        assert doc is not None and doc.content is None and storage.read_content(doc)
        be.put("documents/" + "f" * 32, b"orphan")
        assert storage_migrate.report_orphans(db, "disk") == ["documents/" + "f" * 32]


def _load_script() -> Any:
    path = Path(__file__).resolve().parents[3] / "scripts" / "migrate_files_to_storage.py"
    spec = importlib.util.spec_from_file_location("migrate_files_to_storage", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_script(
    client: TestClient,
    team: Team,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seed_db_files(client, team)
    storage.set_backend(storage.DISK, DiskBackend(tmp_path / "m"))
    mod = _load_script()
    monkeypatch.setattr("sys.argv", ["x", "--target", "disk", "--dry-run"])
    assert mod.main() == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["moved"] == 3 and out["dry_run"] is True
    monkeypatch.setattr("sys.argv", ["x", "--target", "disk"])
    assert mod.main() == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["moved"] == 3 and out["failed"] == 0
    monkeypatch.setattr("sys.argv", ["x"])  # 저장소를 안 정하면 안내하고 끝낸다
    assert mod.main() == 2
    monkeypatch.setattr("sys.argv", ["x", "--orphans", "disk"])
    assert mod.main() == 0
