"""v0.9 지식 처리 캔버스·이미지 색인: 그림 파일 보기, 그림 설명 비용 어림, 처리 순서 모음.

- 빌더(로그인): GET /knowledge-bases/{kb}/images/{file}  — 지식베이스를 볼 수 있는 사람
- 공개 챗: GET /public/apps/{token}/kb-images/{file}?exp=&sig=  — 서버가 붙여 준 24시간 서명 주소
  (로그인한 사용자는 서명 없이도 배포 접근 규칙을 통과하면 열 수 있다. 접근 제한 IP는 전역 가드가 막는다)
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select

from api.core import ratelimit
from api.core.errors import AppError, not_found
from api.deps import EDIT_APPS, VIEW_RUNS, Ctx, CurrentUser, DbDep, require_role
from api.models import Document, KnowledgeBase, StoredFile
from api.routers.common import client_ip
from api.routers.deployments import OptionalUser, _check_access, _load_public
from api.services import kb_images, storage
from api.services import kb_pipeline as pipe
from api.services import knowledge as svc

router = APIRouter(tags=["knowledge-images"])
KbViewers = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="kb"))]
KbBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="kb"))]

CACHE = {
    "Cache-Control": "private, max-age=600",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
}


def _serve(f: StoredFile) -> Response:
    return Response(storage.read_content(f), media_type=f.mime, headers=CACHE)


@router.get("/knowledge-pipeline-templates")
def pipeline_templates(user: CurrentUser) -> list[dict[str, Any]]:
    """처리 캔버스에서 고르는 미리 만들어 둔 처리 순서 4가지."""
    del user
    return pipe.templates()


@router.get("/knowledge-bases/{kb_id}/images/{file_id}")
def kb_image(kb_id: str, file_id: str, ctx: KbViewers) -> Response:
    f = ctx.db.get(StoredFile, file_id)
    if (
        not kb_images.is_kb_image(f)
        or f is None
        or f.workspace_id != ctx.workspace_id
        or not f.filename.startswith(f"{kb_images.FILE_PREFIX}{kb_id}/")
    ):
        raise not_found("그림")
    return _serve(f)


@router.api_route("/public/apps/{token}/kb-images/{file_id}", methods=["GET", "HEAD"])
def public_kb_image(
    token: str,
    file_id: str,
    request: Request,
    db: DbDep,
    user: OptionalUser,
    exp: Annotated[int | None, Query()] = None,
    sig: Annotated[str | None, Query(max_length=128)] = None,
) -> Response:
    if not ratelimit.allow(f"kbimg:{client_ip(request)}", 300):
        raise AppError(429, "그림을 너무 자주 불러요.", "잠시 뒤에 다시 열어 주세요.")
    dep, app, _version = _load_public(db, token)
    signed = (
        exp is not None
        and bool(sig)
        and kb_images.verify_signature(token, file_id, int(exp), str(sig))
    )
    if not signed or dep.access != "public":
        if user is None:
            raise AppError(
                403,
                "그림 주소가 만료됐거나 올바르지 않아요.",
                "챗 화면을 새로고침한 뒤 다시 열어 주세요.",
            )
        _check_access(db, dep, app, user)
    f = db.get(StoredFile, file_id)
    if not kb_images.is_kb_image(f) or f is None or f.workspace_id != app.workspace_id:
        raise not_found("그림")
    return _serve(f)


@router.get("/knowledge-bases/{kb_id}/image-estimate")
def image_estimate(
    kb_id: str,
    ctx: KbBuilders,
    max_images: Annotated[int, Query(ge=1, le=20)] = 20,
    min_size: Annotated[int, Query(ge=50, le=2000)] = 100,
) -> dict[str, Any]:
    """'이미지 설명'을 켜고 다시 나눌 때 그림이 몇 장이고 AI를 몇 번 부르는지·예상 비용(앞의 100개 문서 기준)."""
    from api.routers.knowledge_v08 import internal_kb

    internal_kb(ctx, kb_id)
    kb = ctx.db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise not_found("지식베이스")
    docs = list(
        ctx.db.scalars(
            select(Document).where(Document.kb_id == kb_id).order_by(Document.created_at.desc())
        )
    )
    cfg = {"max_images": max_images, "min_size": min_size}
    est = kb_images.estimate_kb(ctx.db, ctx.workspace_id, docs, cfg)
    saved = pipe.step_of(svc.kb_settings(kb)["pipeline"], "image")
    est["enabled"] = bool(saved.get("enabled"))
    est["budget_message"] = (kb_images.budget_block(ctx.db, ctx.workspace_id) or "").replace(
        "\n", " "
    )
    return est
