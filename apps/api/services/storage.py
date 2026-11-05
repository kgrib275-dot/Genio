"""파일 저장소(v0.8, ADR 0012): 올린 파일·지식 문서의 본문을 어디에 둘지 고른다.

- GENIO_STORAGE=db   (기본) 지금까지처럼 DB 열(content)에 둔다. 아무것도 바뀌지 않는다.
- GENIO_STORAGE=disk 서버 디렉터리(볼륨)에 파일로 둔다(GENIO_STORAGE_DIR).
- GENIO_STORAGE=s3   S3 호환 저장소(AWS S3, MinIO 등)에 둔다(GENIO_S3_*).

행(StoredFile·Document)에는 어느 저장소에 어떤 키로 있는지(storage, storage_key)만 남는다.
그래서 저장소를 바꿔도 이미 올린 파일은 자기가 있는 곳에서 계속 읽히고(섞여 있어도 됨),
scripts/migrate_files_to_storage.py 로 천천히 옮길 수 있다.

비밀값(접근 키·비밀 키)은 로그·오류 문장에 넣지 않는다.
"""

import contextlib
import logging
import os
import re
import tempfile
import uuid
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from api.config import Settings, get_settings
from api.core.errors import AppError

log = logging.getLogger("genio.storage")

DB = "db"
DISK = "disk"
S3 = "s3"
NAMES = (DB, DISK, S3)

# 키는 'files/<32자리 16진수>' 같은 슬래시로 나눈 안전한 조각만 쓴다(.. 와 절대 경로 금지)
_KEY_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MAX_KEY_LEN = 200


class StorageError(AppError):
    """저장소 오류. 항상 '무엇이 문제 + 어떻게 하면 되는지' 두 줄."""

    def __init__(self, message: str, hint: str, status: int = 503) -> None:
        super().__init__(status, message, hint)


def validate_key(key: str) -> str:
    """저장소 키 검사. 경로 탈출(.., 절대 경로, 역슬래시, NUL 등)은 모두 거절한다."""
    if (
        not key
        or len(key) > MAX_KEY_LEN
        or key.startswith("/")
        or "\\" in key
        or "\x00" in key
        or any(not _KEY_SEGMENT.match(seg) or seg in (".", "..") for seg in key.split("/"))
    ):
        raise StorageError(
            "저장소 주소(키)가 올바르지 않아요.",
            "관리자에게 알려 주세요. 파일 주소가 깨졌어요.",
            500,
        )
    return key


class StorageBackend(Protocol):
    name: str

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def size(self, key: str) -> int: ...
    def iter_keys(self, prefix: str = "") -> Iterator[str]: ...


def _missing() -> StorageError:
    return StorageError(
        "저장된 파일을 찾지 못했어요.",
        "파일을 다시 올려 주세요. 계속되면 관리자에게 저장소 점검을 요청하세요.",
        404,
    )


class DiskBackend:
    name = DISK

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        validate_key(key)
        root = self.root.resolve()
        path = (root / key).resolve()
        # 심볼릭 링크 등으로 루트 밖을 가리키면 거절
        try:
            inside = os.path.commonpath([str(root), str(path)]) == str(root)
        except ValueError:  # 드라이브가 다르면(윈도) 루트 밖이다
            inside = False
        if not inside:
            raise StorageError(
                "저장소 주소(키)가 올바르지 않아요.",
                "관리자에게 알려 주세요. 파일 주소가 깨졌어요.",
                500,
            )
        return path

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # 쓰다가 멈춰도 반쪽 파일이 남지 않게 임시 파일에 쓰고 바꿔치기한다
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
        except OSError:
            log.warning("디스크 저장소 쓰기 실패(key=%s)", key)
            raise StorageError(
                "서버 디스크에 파일을 쓰지 못했어요.",
                "디스크 공간과 저장 폴더 권한을 확인해 달라고 관리자에게 요청하세요.",
            ) from None

    def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise _missing() from None
        except OSError:
            raise StorageError(
                "서버 디스크에서 파일을 읽지 못했어요.",
                "잠시 뒤 다시 시도하고, 계속되면 관리자에게 알려 주세요.",
            ) from None

    def delete(self, key: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path(key).unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def size(self, key: str) -> int:
        try:
            return self._path(key).stat().st_size
        except FileNotFoundError:
            raise _missing() from None

    def iter_keys(self, prefix: str = "") -> Iterator[str]:
        root = self.root.resolve()
        if not root.is_dir():
            return
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if name.startswith(".tmp-"):
                    continue
                rel = (Path(dirpath) / name).relative_to(root).as_posix()
                if rel.startswith(prefix):
                    yield rel


class S3Backend:
    name = S3

    def __init__(self, client: Any, bucket: str, prefix: str = "") -> None:
        self.client = client
        self.bucket = bucket
        self.prefix = prefix

    def _k(self, key: str) -> str:
        return f"{self.prefix}{validate_key(key)}"

    @staticmethod
    def _down() -> StorageError:
        # 오류 본문에는 주소·키 정보가 섞일 수 있어 그대로 보여 주지 않는다
        return StorageError(
            "파일 저장소(S3)에 연결하지 못했어요.",
            "저장소 주소·버킷·접근 키 설정을 확인해 달라고 관리자에게 요청하세요.",
        )

    @staticmethod
    def _not_found(exc: Exception) -> bool:
        resp = getattr(exc, "response", None) or {}
        code = str((resp.get("Error") or {}).get("Code", ""))
        status = (resp.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        return code in ("404", "NoSuchKey", "NotFound") or status == 404

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        try:
            self.client.put_object(Bucket=self.bucket, Key=self._k(key), Body=data, **extra)
        except StorageError:
            raise
        except Exception:
            log.warning("S3 저장 실패(key=%s)", key)
            raise self._down() from None

    def get(self, key: str) -> bytes:
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=self._k(key))["Body"]
            data: bytes = body.read()
            return data
        except StorageError:
            raise
        except Exception as exc:
            if self._not_found(exc):
                raise _missing() from None
            log.warning("S3 읽기 실패(key=%s)", key)
            raise self._down() from None

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._k(key))
        except StorageError:
            raise
        except Exception:
            log.warning("S3 삭제 실패(key=%s)", key)
            raise self._down() from None

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._k(key))
            return True
        except StorageError:
            raise
        except Exception as exc:
            if self._not_found(exc):
                return False
            raise self._down() from None

    def size(self, key: str) -> int:
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=self._k(key))
            return int(head["ContentLength"])
        except StorageError:
            raise
        except Exception as exc:
            if self._not_found(exc):
                raise _missing() from None
            raise self._down() from None

    def iter_keys(self, prefix: str = "") -> Iterator[str]:
        try:
            pager = self.client.get_paginator("list_objects_v2")
            for page in pager.paginate(Bucket=self.bucket, Prefix=f"{self.prefix}{prefix}"):
                for obj in page.get("Contents", []):
                    k = str(obj["Key"])
                    yield k[len(self.prefix) :] if k.startswith(self.prefix) else k
        except StorageError:
            raise
        except Exception:
            raise self._down() from None


def make_s3_client(st: Settings) -> Any:
    """설정으로 boto3 S3 클라이언트를 만든다(시험에서는 가짜 클라이언트를 직접 넣는다)."""
    if not st.genio_s3_bucket:
        raise StorageError(
            "S3 버킷 이름이 정해지지 않았어요.",
            "관리자에게 GENIO_S3_BUCKET 설정을 요청하세요.",
            500,
        )
    try:
        import boto3
        from botocore.config import Config
    except ImportError:  # pragma: no cover - 설치 누락
        raise StorageError(
            "S3 저장소 라이브러리(boto3)가 설치되어 있지 않아요.",
            "관리자에게 서버 이미지를 다시 만들어 달라고 요청하세요.",
            500,
        ) from None
    cfg = Config(
        s3={"addressing_style": "path" if st.genio_s3_path_style else "auto"},
        connect_timeout=5,
        read_timeout=30,
        retries={"max_attempts": 2},
    )
    return boto3.client(
        "s3",
        endpoint_url=st.genio_s3_endpoint_url or None,
        region_name=st.genio_s3_region or None,
        aws_access_key_id=st.genio_s3_access_key or None,
        aws_secret_access_key=st.genio_s3_secret_key or None,
        config=cfg,
    )


def ensure_bucket(client: Any, bucket: str) -> bool:
    """버킷이 없으면 만든다. 새로 만들었으면 True. (옮기기 도구의 --init-bucket 에서만 쓴다)"""
    try:
        client.head_bucket(Bucket=bucket)
        return False
    except Exception as exc:
        resp = getattr(exc, "response", None) or {}
        status = (resp.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        code = str((resp.get("Error") or {}).get("Code", ""))
        if status != 404 and code not in ("404", "NoSuchBucket", "NotFound"):
            raise S3Backend._down() from None
    try:
        client.create_bucket(Bucket=bucket)
    except Exception:
        raise S3Backend._down() from None
    return True


# 시험(그리고 필요하면 운영 코드)이 가짜 저장소를 끼워 넣는 자리
_overrides: dict[str, StorageBackend] = {}


def set_backend(name: str, backend: StorageBackend | None) -> None:
    """이름에 해당하는 저장소를 직접 지정한다(None이면 설정값으로 되돌림)."""
    if backend is None:
        _overrides.pop(name, None)
    else:
        _overrides[name] = backend
    _build.cache_clear()


@lru_cache(maxsize=8)
def _build(name: str) -> StorageBackend:
    st = get_settings()
    if name == DISK:
        return DiskBackend(st.genio_storage_dir)
    if name == S3:
        prefix = st.genio_s3_prefix.strip("/")
        return S3Backend(make_s3_client(st), st.genio_s3_bucket, f"{prefix}/" if prefix else "")
    raise StorageError(
        "알 수 없는 저장소 종류예요.", "GENIO_STORAGE는 db, disk, s3 중 하나여야 해요.", 500
    )


def backend_named(name: str) -> StorageBackend:
    if name in _overrides:
        return _overrides[name]
    return _build(name)


def configured_name() -> str:
    name = (get_settings().genio_storage or DB).strip().lower()
    return name if name in NAMES else DB


def configured_backend() -> StorageBackend | None:
    """새 파일을 둘 저장소. 기본(db)이면 None(= 행의 content 열에 둔다)."""
    name = configured_name()
    return None if name == DB else backend_named(name)


# ---------------- 행(StoredFile·Document) 단위 도우미 ----------------
def empty_value(obj: Any) -> bytes | None:
    """DB 열을 비울 때 쓸 값(content가 NULL을 허용하면 None, 아니면 빈 바이트)."""
    return None if obj.__table__.c.content.nullable else b""


def new_key(kind: str) -> str:
    return f"{kind}/{uuid.uuid4().hex}"


def write_content(obj: Any, data: bytes, *, kind: str, content_type: str | None = None) -> None:
    """obj(StoredFile·Document)의 본문을 설정된 저장소에 쓰고 어디에 있는지 적는다."""
    backend = configured_backend()
    if backend is None:
        obj.content = data
        obj.storage = DB
        obj.storage_key = None
        return
    key = new_key(kind)
    backend.put(key, data, content_type)
    obj.content = empty_value(obj)
    obj.storage = backend.name
    obj.storage_key = key


def read_content(obj: Any) -> bytes:
    """obj의 본문. 저장소가 바뀌었어도 그 파일이 있는 곳에서 읽는다."""
    storage = getattr(obj, "storage", DB) or DB
    key = getattr(obj, "storage_key", None)
    if storage == DB or not key:
        return bytes(obj.content or b"")
    return backend_named(storage).get(key)


def delete_content(obj: Any) -> None:
    """행을 지울 때 저장소의 본문도 지운다(실패해도 행 삭제는 막지 않는다)."""
    storage = getattr(obj, "storage", DB) or DB
    key = getattr(obj, "storage_key", None)
    if storage == DB or not key:
        return
    try:
        backend_named(storage).delete(key)
    except AppError:
        log.warning("저장소 파일 삭제 실패(storage=%s, key=%s)", storage, key)


def locations(objs: Any) -> list[tuple[str, str]]:
    """지울 행들의 (저장소 이름, 키). 행 삭제를 커밋한 뒤에 purge()로 본문을 지운다."""
    out: list[tuple[str, str]] = []
    for o in objs:
        storage = getattr(o, "storage", DB) or DB
        key = getattr(o, "storage_key", None)
        if storage != DB and key:
            out.append((storage, key))
    return out


def purge(locs: list[tuple[str, str]]) -> None:
    for storage, key in locs:
        try:
            backend_named(storage).delete(key)
        except AppError:
            log.warning("저장소 파일 삭제 실패(storage=%s, key=%s)", storage, key)
