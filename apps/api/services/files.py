"""파일 올리기(앱 입력·챗 첨부). 최대 15MB, 문서·이미지·텍스트만."""

from typing import Any

from fastapi import UploadFile
from sqlalchemy.orm import Session

from api.core.errors import AppError
from api.models import StoredFile
from api.services import storage

MAX_FILE_BYTES = 15 * 1024 * 1024
ALLOWED_EXT = (
    ".pdf",
    ".txt",
    ".md",
    ".markdown",
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".htm",
    ".csv",
    ".json",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
)


def file_dict(f: StoredFile) -> dict[str, Any]:
    return {
        "id": f.id,
        "filename": f.filename,
        "mime": f.mime,
        "size": f.size,
        "created_at": f.created_at,
    }


async def save_upload(
    db: Session,
    workspace_id: str,
    file: UploadFile,
    *,
    app_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    name = (file.filename or "file").strip()[:300]
    if not name.lower().endswith(ALLOWED_EXT):
        raise AppError(
            415,
            "올릴 수 없는 파일 형식이에요.",
            "PDF, 텍스트, CSV, JSON, 이미지 파일만 올릴 수 있어요.",
        )
    content = await file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise AppError(413, "파일이 너무 커요(최대 15MB).", "더 작은 파일로 나눠 올려 주세요.")
    f = StoredFile(
        workspace_id=workspace_id,
        app_id=app_id,
        filename=name,
        mime=file.content_type or "application/octet-stream",
        size=len(content),
        content=b"",
        created_by=user_id,
    )
    # 설정된 저장소(db·disk·s3)에 본문을 쓰고, 어디에 있는지 행에 적는다
    storage.write_content(f, content, kind="files", content_type=f.mime)
    db.add(f)
    db.commit()
    return file_dict(f)
