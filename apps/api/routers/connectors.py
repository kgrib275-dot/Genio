"""커넥터 정의와 연결 정보(자격증명). 값은 암호화 저장하고 응답에는 마스킹만 내보낸다."""

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.connectors import runtime
from api.core.audit import audit
from api.core.crypto import decrypt_json, encrypt_json, mask
from api.core.errors import AppError, not_found
from api.deps import ANY_MEMBER, EDIT_APPS, MANAGE_SECRETS, Ctx, require_role
from api.market import service as market
from api.models import ConnectorCredential, ConnectorDefinition, Workspace
from nodes import NodeError

router = APIRouter(tags=["connectors"])
Members = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]
Builders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]
SecretManagers = Annotated[Ctx, Depends(require_role(MANAGE_SECRETS))]
_HOST_RE = re.compile(r"^[a-z0-9.\-:\[\]]{1,253}$")


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


# ---------------- 연결 테스트(기능 정의서 §4) ----------------
@router.post("/workspaces/{ws}/connectors/credentials/{credential_id}/test")
def test_credential(ws: str, credential_id: str, ctx: Builders) -> dict[str, Any]:
    """연결 정보가 실제로 되는지 확인한다(빌더도 쓸 수 있다: 값은 보지 못하고 결과만 본다)."""
    cred = ctx.db.get(ConnectorCredential, credential_id)
    if cred is None or cred.workspace_id != ws:
        raise not_found("연결 정보")
    try:
        result = runtime.test_credential(ctx.db, ws, credential_id)
    except NodeError as exc:
        result = {"ok": False, "checked": False, "message": exc.message}
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="credential.test",
        target_type="connector_credential",
        target_id=credential_id,
        meta={"ok": bool(result.get("ok"))},
    )
    ctx.db.commit()
    return result


# ---------------- 허용할 내부 주소(사내 DB 등) ----------------
class PrivateHostsIn(BaseModel):
    hosts: list[str] = Field(default_factory=list, max_length=20)


def _clean_hosts(hosts: list[str]) -> list[str]:
    out: list[str] = []
    for h in hosts:
        v = h.strip().lower()
        if not v:
            continue
        if not _HOST_RE.match(v):
            raise AppError(
                422,
                f"주소 형식이 올바르지 않아요: {h[:60]}",
                "호스트 이름이나 IP만 적으세요(예: db.internal.example.com, 10.0.0.5).",
            )
        if _always_blocked(v):
            raise AppError(
                422,
                f"'{v}'는 허용할 수 없어요.",
                "자기 자신(localhost)·서비스 내부 이름·클라우드 메타데이터 주소는 언제나 막혀 있어요.",
            )
        if v not in out:
            out.append(v)
    return out


# 제니오 자신의 내부 서비스 이름(docker compose)과 자기 자신을 가리키는 주소는 어떤 관리자도 열 수 없다
_INTERNAL_NAMES = {
    "localhost",
    "ip6-localhost",
    "0.0.0.0",  # noqa: S104
    "::",
    "::1",
    "169.254.169.254",
    "metadata.google.internal",
    "postgres",
    "redis",
    "api",
    "web",
    "worker",
    "scheduler",
    "sandbox",
    "host.docker.internal",
    "gateway.docker.internal",
}


def _always_blocked(host: str) -> bool:
    import ipaddress

    h = host.strip().strip("[]").lower().rstrip(".")
    if h in _INTERNAL_NAMES or h.startswith("127.") or h.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        # 0x7f000001·2130706433 같은 다른 표기도 막는다
        try:
            ip = ipaddress.ip_address(int(h, 0))
        except ValueError:
            return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast)


@router.get("/workspaces/{ws}/connectors/private-hosts")
def get_private_hosts(ws: str, ctx: SecretManagers) -> dict[str, Any]:
    w = ctx.db.get(Workspace, ws)
    return {"hosts": runtime.allowed_private_hosts(ctx.db, ws) if w else []}


@router.put("/workspaces/{ws}/connectors/private-hosts")
def put_private_hosts(ws: str, body: PrivateHostsIn, ctx: SecretManagers) -> dict[str, Any]:
    # 내부 주소를 여는 일은 서비스 전체에 영향을 주므로 인스턴스 관리자(가장 먼저 만든 워크스페이스 소유자)만 한다
    from api.services.system import is_instance_admin

    if not is_instance_admin(ctx.db, ctx.user.id):
        raise AppError(
            403,
            "내부 주소 허용은 서비스 전체 관리자만 바꿀 수 있어요.",
            "서비스 관리자(가장 먼저 만든 워크스페이스의 소유자)에게 요청하세요.",
        )
    w = ctx.db.get(Workspace, ws)
    if w is None:
        raise not_found("워크스페이스")
    hosts = _clean_hosts(body.hosts)
    w.settings = {**(w.settings or {}), "allow_private_hosts": hosts}
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="workspace.private_hosts",
        target_type="workspace",
        target_id=ws,
        meta={"hosts": hosts},
    )
    ctx.db.commit()
    return {"hosts": hosts}
