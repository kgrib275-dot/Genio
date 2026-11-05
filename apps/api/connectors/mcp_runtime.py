"""MCP 연결 정보(connector key 'mcp_server')로 서버를 부르는 엔진 쪽 도우미.

비밀값(주소·토큰)은 여기서만 풀어 쓰고, 오류 문장에서는 지운다.
"""

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.connectors.mcp_client import McpClient, McpServer, server_from_secrets
from api.core.crypto import decrypt_json, redact
from api.models import ConnectorCredential, ConnectorDefinition
from nodes import NodeError

CREDENTIAL_KEY = "mcp_server"
TOOLS_CACHE_SECONDS = 60.0
_tools_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def load_server(db: Session, workspace_id: str, credential_id: str) -> tuple[McpServer, list[str]]:
    """연결 정보에서 서버를 꺼낸다. (서버, 오류 문장에서 지울 비밀값들)"""
    cred = db.get(ConnectorCredential, credential_id)
    if cred is None or cred.workspace_id != workspace_id:
        raise NodeError("MCP 연결 정보를 찾을 수 없어요. 단계 설정에서 다시 골라 주세요.")
    definition = db.scalar(
        select(ConnectorDefinition).where(ConnectorDefinition.id == cred.definition_id)
    )
    if definition is None or definition.key != CREDENTIAL_KEY:
        raise NodeError("MCP 서버 연결 정보가 아니에요. 'MCP 서버'로 만든 연결 정보를 골라 주세요.")
    secrets = decrypt_json(cred.secret_encrypted)
    server = server_from_secrets(secrets)
    hidden = [server.url, server.token]
    return server, [v for v in hidden if v]


def list_tools(
    db: Session, workspace_id: str, credential_id: str, *, use_cache: bool = True
) -> list[dict[str, Any]]:
    now = time.monotonic()
    cached = _tools_cache.get(credential_id)
    if use_cache and cached and now - cached[0] < TOOLS_CACHE_SECONDS:
        return cached[1]
    server, hidden = load_server(db, workspace_id, credential_id)
    client = McpClient(server)
    try:
        tools = client.list_tools()
    except NodeError as exc:
        raise NodeError(redact(exc.message, hidden), retryable=exc.retryable) from None
    finally:
        client.close()
    _tools_cache[credential_id] = (now, tools)
    return tools


def _scrub(value: Any, hidden: list[str]) -> Any:
    """도구 결과 안에 서버가 되돌려 보낸 비밀값(주소·토큰)이 있으면 마스킹한다."""
    if isinstance(value, str):
        return redact(value, hidden)
    if isinstance(value, list):
        return [_scrub(v, hidden) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v, hidden) for k, v in value.items()}
    return value


def forget(credential_id: str) -> None:
    _tools_cache.pop(credential_id, None)


def call_tool(
    db: Session,
    workspace_id: str,
    credential_id: str,
    tool: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    server, hidden = load_server(db, workspace_id, credential_id)
    client = McpClient(server)
    try:
        result: dict[str, Any] = _scrub(client.call_tool(tool, arguments), hidden)
        return result
    except NodeError as exc:
        raise NodeError(redact(exc.message, hidden), retryable=exc.retryable) from None
    finally:
        client.close()
