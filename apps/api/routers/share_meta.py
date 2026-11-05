"""공유 링크 미리보기(v0.8): 메신저 로봇용 HTML과 썸네일 그림. 로그인 없이 읽는 공개 경로다."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from api.deps import DbDep
from api.models import StoredFile
from api.routers.common import public_origin
from api.services import share_meta as svc

router = APIRouter(tags=["share-meta"])
CACHE = {"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff"}


@router.api_route(
    "/public/share/{token}",
    methods=["GET", "HEAD"],
    response_class=HTMLResponse,
    include_in_schema=False,
)
def share_page(token: str, request: Request, db: DbDep) -> HTMLResponse:
    """공유 링크(또는 '-' = 일반 소개)의 미리보기 HTML."""
    meta = svc.build_meta(db, token, public_origin(request))
    return HTMLResponse(svc.render_html(meta), headers=CACHE)


@router.get("/public/share-meta/{token}")
def share_meta_json(token: str, request: Request, db: DbDep) -> dict[str, object]:
    """화면(SPA)이 탭 제목을 앱 이름으로 바꿀 때 쓰는 같은 정보."""
    meta = svc.build_meta(db, token, public_origin(request))
    return {k: meta[k] for k in ("title", "description", "image", "url")}


def _default_image() -> Response:
    try:
        data = svc.DEFAULT_IMAGE.read_bytes()
    except OSError:
        return Response(status_code=404)
    return Response(data, media_type="image/png", headers=CACHE)


@router.api_route("/public/og-default.png", methods=["GET", "HEAD"], include_in_schema=False)
def og_default() -> Response:
    return _default_image()


@router.api_route(
    "/public/apps/{token}/share-logo", methods=["GET", "HEAD"], include_in_schema=False
)
def share_logo(token: str, db: DbDep) -> Response:
    """앱 관리자가 올린 웹앱 로고. 없거나 올바르지 않으면 404(화면은 기본 아이콘을 쓴다)."""
    from sqlalchemy import select

    from api.models import App, Deployment
    from api.routers.deployments import appearance_of

    dep = db.scalar(select(Deployment).where(Deployment.public_token == token))
    app = db.get(App, dep.app_id) if dep is not None else None
    file_id = appearance_of(dep)["share_logo"] if dep is not None else ""
    f = db.get(StoredFile, file_id) if file_id else None
    if app is None or f is None or not svc.logo_ok(f, app.workspace_id):
        return Response(status_code=404)
    return Response(f.content, media_type=f.mime, headers=CACHE)


@router.api_route(
    "/public/apps/{token}/share-image", methods=["GET", "HEAD"], include_in_schema=False
)
def share_image(token: str, db: DbDep) -> Response:
    """앱 관리자가 올린 썸네일(누구나 열 수 있는 앱만). 없으면 기본 그림."""
    from api.routers.deployments import appearance_of

    found = svc.public_deployment(db, token)
    if found is None:
        return _default_image()
    dep, app = found
    file_id = appearance_of(dep)["share_image"]
    f = db.get(StoredFile, file_id) if file_id else None
    if f is None or not svc.image_ok(f, app.workspace_id):
        return _default_image()
    return Response(f.content, media_type=f.mime, headers=CACHE)
