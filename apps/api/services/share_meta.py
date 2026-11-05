"""공유 링크 미리보기(v0.8): 카카오톡·슬랙·메일 등에 링크를 붙였을 때 뜨는 제목·소개 문구·썸네일.

메신저의 미리보기 로봇은 자바스크립트를 실행하지 않아서, 화면(SPA)과 별개로 서버가
제목·소개·썸네일이 들어 있는 HTML(Open Graph)을 내준다(nginx가 로봇에게만 이쪽으로 보낸다).
- 누구나 열 수 있는('public') 앱만 앱 이름·소개·썸네일을 보여 준다. 멤버 전용 앱은 일반 소개만 나간다.
- 앱 관리자가 배포 설정에서 공유 제목·소개 문구·썸네일을 직접 정할 수 있다.
"""

import html
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import App, Deployment, StoredFile
from api.services.app_config import merged_features

SITE_NAME = "제니오"
DEFAULT_TITLE = "제니오 — 말로 만드는 나만의 앱"
DEFAULT_DESCRIPTION = (
    "말로 요청하면 일하는 앱이 만들어져요. 챗봇·자동화·사람 승인까지 코딩 없이 한 곳에서."
)
DEFAULT_IMAGE = Path(__file__).resolve().parent.parent / "assets" / "og-default.png"
IMAGE_MIMES = ("image/png", "image/jpeg", "image/webp", "image/gif")
MAX_IMAGE_BYTES = 2 * 1024 * 1024
TITLE_MAX = 60
DESCRIPTION_MAX = 160


def clip(text: str, limit: int) -> str:
    one_line = " ".join((text or "").split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1].rstrip() + "…"


def image_ok(f: StoredFile | None, workspace_id: str) -> bool:
    return (
        f is not None
        and f.workspace_id == workspace_id
        and f.mime in IMAGE_MIMES
        and 0 < f.size <= MAX_IMAGE_BYTES
    )


def public_deployment(db: Session, token: str) -> tuple[Deployment, App] | None:
    """누구나 열 수 있는 배포만 돌려준다(멤버 전용·없는 링크는 None)."""
    if not token or token == "-":  # noqa: S105 - "-"는 일반 소개를 뜻하는 자리표시자
        return None
    dep = db.scalar(select(Deployment).where(Deployment.public_token == token))
    if dep is None or dep.access != "public":
        return None
    app = db.get(App, dep.app_id)
    return (dep, app) if app is not None else None


def build_meta(db: Session, token: str, origin: str) -> dict[str, Any]:
    """미리보기에 쓸 제목·소개·그림 주소·링크."""
    from api.routers.deployments import appearance_of

    found = public_deployment(db, token)
    if found is None:
        return {
            "title": DEFAULT_TITLE,
            "description": DEFAULT_DESCRIPTION,
            "image": f"{origin}/api/v1/public/og-default.png",
            "url": f"{origin}/",
            "custom": False,
        }
    dep, app = found
    look = appearance_of(dep)
    features = merged_features(app.features)
    title = look["share_title"] or app.name
    description = (
        look["share_description"]
        or app.description
        or features.get("opening_statement")
        or DEFAULT_DESCRIPTION
    )
    return {
        "title": clip(str(title), TITLE_MAX),
        "description": clip(str(description), DESCRIPTION_MAX),
        "image": f"{origin}/api/v1/public/apps/{token}/share-image",
        "url": f"{origin}/share/{token}",
        "custom": True,
    }


def render_html(meta: dict[str, Any]) -> str:
    """메신저 로봇이 읽는 HTML. 값은 모두 이스케이프한다."""
    e = html.escape
    t, d, img, url = (e(str(meta[k]), quote=True) for k in ("title", "description", "image", "url"))
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{t}</title>
<meta name="description" content="{d}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:locale" content="ko_KR">
<meta property="og:title" content="{t}">
<meta property="og:description" content="{d}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{img}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{t}">
<meta name="twitter:description" content="{d}">
<meta name="twitter:image" content="{img}">
</head>
<body><h1>{t}</h1><p>{d}</p><p><a href="{url}">열기</a></p></body>
</html>
"""
