"""실행이 만든 파일 내려받기(v0.9).

- 로그인한 사람: 실행 기록의 파일 목록과 내려받기(실행 기록을 볼 수 있는 역할).
- 공유 링크: 서버가 답·결과에 실어 보낸 서명 링크로만 내려받는다(접근 권한 규칙도 그대로 확인).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response

from api.core import ratelimit
from api.core.errors import AppError, not_found
from api.deps import DbDep
from api.models import Run, StoredFile
from api.routers.common import client_ip
from api.routers.deployments import OptionalUser, _check_access, _load_public
from api.routers.runs import RunViewers
from api.services import file_links, run_files, storage

router = APIRouter(tags=["run-files"])

# 내려줄 때 그대로 인정하는 형식(그 밖은 내려받기 전용 일반 파일로)
SAFE_MIMES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "text/plain; charset=utf-8",
    "text/markdown; charset=utf-8",
    "text/csv; charset=utf-8",
    "application/json",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
ID_LEN = Annotated[str, Query(max_length=64)]


def _response(f: StoredFile, *, inline: bool) -> Response:
    try:
        content = storage.read_content(f)
    except AppError:
        raise AppError(
            404,
            "파일을 읽지 못했어요.",
            "파일 저장소가 바뀌었거나 지워졌는지 관리자에게 확인하세요.",
        ) from None
    mime = f.mime if f.mime in SAFE_MIMES else "application/octet-stream"
    show_inline = inline and mime in run_files.IMAGE_MIMES
    headers = {
        "Content-Disposition": run_files.content_disposition(f.filename, inline=show_inline),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=300",
        # 혹시 열리더라도 스크립트가 돌지 않게
        "Content-Security-Policy": "default-src 'none'; img-src 'self' data:; sandbox",
    }
    return Response(content, media_type=mime, headers=headers)


# ---------------- 로그인한 사람(실행 기록) ----------------
@router.get("/runs/{run_id}/files")
def list_run_files(run_id: str, ctx: RunViewers) -> dict[str, Any]:
    run = ctx.db.get(Run, run_id)
    if run is None:
        raise not_found("실행 기록")
    return {"files": run_files.files_of_run(ctx.db, run, ctx.workspace_id)}


@router.get("/runs/{run_id}/files/{file_id}")
def download_run_file(run_id: str, file_id: str, ctx: RunViewers, inline: bool = False) -> Response:
    run = ctx.db.get(Run, run_id)
    if run is None:
        raise not_found("실행 기록")
    if file_id not in {i["id"] for i in run_files.files_of_run(ctx.db, run, ctx.workspace_id)}:
        raise not_found("파일")
    f = ctx.db.get(StoredFile, file_id)
    if f is None:
        raise not_found("파일")
    return _response(f, inline=inline)


# ---------------- 공유 링크(서명된 링크) ----------------
@router.get("/public/apps/{token}/files/{file_id}")
def public_file(
    token: str,
    file_id: str,
    request: Request,
    db: DbDep,
    user: OptionalUser,
    sig: ID_LEN = "",
    exp: int = 0,
    inline: bool = False,
) -> Response:
    dep, app, _ = _load_public(db, token)
    _check_access(db, dep, app, user)
    if not ratelimit.allow(f"file:{app.id}:{client_ip(request)}", 120):
        raise AppError(429, "파일 요청이 너무 많아요.", "잠시 뒤 다시 내려받아 주세요.")
    if not file_links.verify(app.id, file_id, sig, exp):
        raise AppError(
            403,
            "내려받기 링크가 만료됐거나 맞지 않아요.",
            "챗이나 결과 화면에서 파일을 다시 열어 주세요.",
        )
    f = db.get(StoredFile, file_id)
    if f is None or f.app_id != app.id or f.workspace_id != app.workspace_id:
        raise not_found("파일")
    return _response(f, inline=inline)
