"""커넥터 정의와 연결 정보(자격증명). 값은 암호화 저장하고 응답에는 마스킹만 내보낸다."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.core.audit import audit
from api.core.crypto import decrypt_json, encrypt_json, mask
from api.core.errors import AppError, not_found
from api.deps import ANY_MEMBER, EDIT_APPS, MANAGE_SECRETS, Ctx, require_role
from api.market import service as market
from api.models import ConnectorCredential, ConnectorDefinition

router = APIRouter(tags=["connectors"])
Members = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]
Builders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]
SecretManagers = Annotated[Ctx, Depends(require_role(MANAGE_SECRETS))]


def _installed_definitions(ctx: Ctx) -> dict[str, ConnectorDefinition]:
    out: dict[str, ConnectorDefinition] = {}
    for item in market.installed_items(ctx.db, ctx.workspace_id, "connector"):
        d = ctx.db.scalar(
            select(ConnectorDefinition).where(
                ConnectorDefinition.key == item.key, ConnectorDefinition.version == item.version
            )
        )
        if d is not None:
            out[d.key] = d
    return out


@router.get("/workspaces/{ws}/connectors/definitions")
def definitions(ws: str, ctx: Members) -> list[dict[str, Any]]:
    return [
        {
            "id": d.id,
            "key": d.key,
            "name": d.name,
            "version": d.version,
            "source": d.source,
            "manifest": d.manifest,
        }
        for d in _installed_definitions(ctx).values()
    ]


def _cred(c: ConnectorCredential, d: ConnectorDefinition | None) -> dict[str, Any]:
    try:
        secrets = decrypt_json(c.secret_encrypted)
        masked = {k: mask(str(v)) for k, v in secrets.items()}
    except ValueError:
        masked = {}
    return {
        "id": c.id,
        "definition_id": c.definition_id,
        "connector_key": d.key if d else "",
        "connector_name": d.name if d else "",
        "name": c.name,
        "created_at": c.created_at,
        "secrets_masked": masked,
    }


@router.get("/workspaces/{ws}/connectors/credentials")
def list_credentials(ws: str, ctx: Builders) -> list[dict[str, Any]]:
    rows = ctx.db.execute(
        select(ConnectorCredential, ConnectorDefinition)
        .join(ConnectorDefinition, ConnectorDefinition.id == ConnectorCredential.definition_id)
        .where(ConnectorCredential.workspace_id == ws)
        .order_by(ConnectorCredential.created_at)
    ).all()
    return [_cred(c, d) for c, d in rows]


class CredentialIn(BaseModel):
    connector_key: str
    name: str = Field(min_length=1, max_length=100)
    secrets: dict[str, str]


@router.post("/workspaces/{ws}/connectors/credentials")
def create_credential(ws: str, body: CredentialIn, ctx: SecretManagers) -> dict[str, Any]:
    definition = _installed_definitions(ctx).get(body.connector_key)
    if definition is None:
        raise AppError(404, "설치되지 않은 서비스예요.", "마켓에서 서비스를 먼저 설치하세요.")
    required = definition.manifest.get("requires", {}).get("credentials", [])
    missing = [
        r.get("label") or r["key"]
        for r in required
        if r.get("required", True) and not body.secrets.get(r["key"])
    ]
    if missing:
        raise AppError(
            422, f"빠진 값이 있어요: {', '.join(missing)}", "모든 칸을 채운 뒤 저장하세요."
        )
    allowed = {r["key"] for r in required}
    secrets = {k: v.strip() for k, v in body.secrets.items() if k in allowed}
    cred = ConnectorCredential(
        workspace_id=ws,
        definition_id=definition.id,
        name=body.name,
        secret_encrypted=encrypt_json(secrets),
        created_by=ctx.user.id,
    )
    ctx.db.add(cred)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="credential.create",
        target_type="connector_credential",
        target_id=cred.id,
        meta={"connector": definition.key, "name": body.name},
    )
    ctx.db.commit()
    return _cred(cred, definition)


@router.delete("/workspaces/{ws}/connectors/credentials/{credential_id}", status_code=204)
def delete_credential(ws: str, credential_id: str, ctx: SecretManagers) -> Response:
    cred = ctx.db.get(ConnectorCredential, credential_id)
    if cred is None or cred.workspace_id != ws:
        raise not_found("연결 정보")
    ctx.db.delete(cred)
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="credential.delete",
        target_type="connector_credential",
        target_id=credential_id,
    )
    ctx.db.commit()
    return Response(status_code=204)
