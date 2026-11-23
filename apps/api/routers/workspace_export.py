"""워크스페이스 전체 내보내기(해지·이관 대비). 앱과 표 데이터를 zip 한 파일로 내려받는다. 비밀값은 넣지 않는다."""

import io
import json
import re
import zipfile
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from api.core.audit import audit
from api.deps import MANAGE_MEMBERS, Ctx, require_role
from api.models import App, DataTable, Workspace
from api.services import data_tables as table_svc
from api.services.app_config import merged_features

router = APIRouter(tags=["workspaces"])
Managers = Annotated[Ctx, Depends(require_role(MANAGE_MEMBERS))]

README = """제니오 워크스페이스 내보내기

apps/    앱마다 파일 하나(JSON). 제니오의 '앱 가져오기'로 다시 불러올 수 있어요.
tables/  표마다 파일 하나(CSV). 엑셀로 열 수 있어요.

보안을 위해 AI 키·연결 정보·비밀 값은 들어 있지 않아요. 다시 불러온 뒤 새로 연결해 주세요.
"""


def _safe(name: str, used: set[str]) -> str:
    base = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name).strip(" .") or "이름없음"
    out, n = base[:80], 2
    while out in used:
        out = f"{base[:76]}-{n}"
        n += 1
    used.add(out)
    return out


@router.get("/workspaces/{ws}/export")
def export_workspace(ws: str, ctx: Managers) -> Response:
    db = ctx.db
    w = db.get(Workspace, ws)
    buf = io.BytesIO()
    used_apps: set[str] = set()
    used_tables: set[str] = set()
    n_apps = n_tables = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README)
        for app in db.scalars(select(App).where(App.workspace_id == ws).order_by(App.name)):
            data = {
                "genio_version": "0.2",
                "app": {
                    "name": app.name,
                    "type": app.type,
                    "description": app.description,
                    "icon": app.icon,
                    "features": merged_features(app.features),
                },
                "graph": app.draft_graph or {},
                # 값은 빼고 이름만 남긴다(비밀이 섞여 있을 수 있어서)
                "env_vars": [
                    {"key": v["key"], "value": "", "secret": True} for v in (app.env_vars or [])
                ],
            }
            z.writestr(
                f"apps/{_safe(app.name, used_apps)}.json",
                json.dumps(data, ensure_ascii=False, indent=2),
            )
            n_apps += 1
        for t in db.scalars(select(DataTable).where(DataTable.workspace_id == ws)):
            z.writestr(f"tables/{_safe(t.name, used_tables)}.csv", table_svc.export_csv(db, t))
            n_tables += 1
    audit(
        db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="workspace.export",
        target_type="workspace",
        target_id=ws,
        meta={"apps": n_apps, "tables": n_tables},
    )
    db.commit()
    name = quote(f"{(w.name if w else 'genio')}-내보내기.zip")
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"},
    )
