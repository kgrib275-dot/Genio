"""스킬(업무 요령): 목록·만들기·SKILL.md 가져오기·고치기·지우기. 제작자 이상."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Response, UploadFile
from pydantic import BaseModel, Field

from api.core.audit import audit
from api.core.errors import AppError, not_found
from api.deps import EDIT_APPS, Ctx, require_role
from api.models import Workspace
from api.services import skills as svc

router = APIRouter(tags=["skills"])
WsBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]


class SkillIn(BaseModel):
    name: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=1000)
    body: str = Field(default="", max_length=svc.MAX_BODY * 2)
    # SKILL.md 글을 그대로 붙여 넣으면 앞머리에서 이름·설명을 읽는다
    skill_md: str = Field(default="", max_length=svc.MAX_BODY * 2)


def _ws(ctx: Ctx, ws: str) -> Workspace:
    w = ctx.db.get(Workspace, ws)
    if w is None:
        raise not_found("워크스페이스")
    return w


def _log(ctx: Ctx, ws: str, action: str, skill: dict[str, Any]) -> None:
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action=action,
        target_type="skill",
        target_id=str(skill.get("id")),
        meta={"name": skill.get("name")},
    )
    ctx.db.commit()


@router.get("/workspaces/{ws}/skills")
def list_skills(ws: str, ctx: WsBuilders) -> dict[str, Any]:
    return {"skills": svc.list_skills(_ws(ctx, ws)), "max_skills": svc.MAX_SKILLS}


@router.get("/workspaces/{ws}/skills/{skill_id}")
def get_skill(ws: str, skill_id: str, ctx: WsBuilders) -> dict[str, Any]:
    return dict(svc.get_skill(_ws(ctx, ws), skill_id))


def _from_body(body: SkillIn) -> dict[str, Any]:
    if body.skill_md.strip():
        return dict(svc.parse_skill_md(body.skill_md))
    return {"name": body.name, "description": body.description, "body": body.body}


@router.post("/workspaces/{ws}/skills", status_code=201)
def create_skill(ws: str, body: SkillIn, ctx: WsBuilders) -> dict[str, Any]:
    item = svc.save(ctx.db, _ws(ctx, ws), _from_body(body))
    _log(ctx, ws, "skill.create", item)
    return item


@router.post("/workspaces/{ws}/skills/import", status_code=201)
async def import_skill(
    ws: str, ctx: WsBuilders, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    content = await file.read(svc.MAX_ZIP_BYTES + 1)
    fname = (file.filename or "").lower()
    if fname.endswith((".zip", ".skill")):
        data = svc.skill_from_zip(content)
    elif fname.endswith((".md", ".markdown", ".txt")):
        if len(content) > svc.MAX_BODY * 2:
            raise AppError(413, "SKILL.md가 너무 커요.", "본문을 줄이거나 나눠서 올려 주세요.")
        data = svc.parse_skill_md(content.decode("utf-8", errors="replace"))
    else:
        raise AppError(
            422, "SKILL.md나 .zip 파일만 올릴 수 있어요.", "파일 형식을 확인해 다시 올려 주세요."
        )
    item = svc.save(ctx.db, _ws(ctx, ws), data)
    _log(ctx, ws, "skill.import", item)
    return item


@router.put("/workspaces/{ws}/skills/{skill_id}")
def update_skill(ws: str, skill_id: str, body: SkillIn, ctx: WsBuilders) -> dict[str, Any]:
    item = svc.save(ctx.db, _ws(ctx, ws), _from_body(body), skill_id)
    _log(ctx, ws, "skill.update", item)
    return item


@router.delete("/workspaces/{ws}/skills/{skill_id}", status_code=204)
def delete_skill(ws: str, skill_id: str, ctx: WsBuilders) -> Response:
    w = _ws(ctx, ws)
    item = dict(svc.get_skill(w, skill_id))
    svc.delete(ctx.db, w, skill_id)
    _log(ctx, ws, "skill.delete", item)
    return Response(status_code=204)
