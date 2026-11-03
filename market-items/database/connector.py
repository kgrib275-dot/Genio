"""데이터베이스 커넥터. 플랫폼의 net.sql_query·sql_execute로만 접속한다(호스트 검사·읽기 전용·시간 제한)."""

from typing import Any


def query(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    return net.sql_query(secrets, str(params["sql"]), params.get("params") or {})


def execute(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    return net.sql_execute(secrets, str(params["sql"]), params.get("params") or {})


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    net.sql_query(secrets, "SELECT 1 AS ok", {})
    return {"message": "데이터베이스에 접속했어요."}
