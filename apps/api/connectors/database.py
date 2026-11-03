"""데이터베이스(PostgreSQL·MySQL) 접속. 마켓의 database 커넥터가 net.sql_query/sql_execute로만 쓴다.

- 호스트는 외부 호출과 같은 규칙으로 검사한다(사설·내부 IP 차단). 워크스페이스 관리자가
  '허용할 내부 호스트'에 올린 이름만 예외다.
- 조회(query)는 SELECT/WITH 한 문장만, 읽기 전용 거래·시간 제한·최대 500행.
- 실행(execute)은 INSERT/UPDATE/DELETE 한 문장만(DDL 금지).
- 값은 %(이름)s 자리에 따로 넘긴다(문자열을 이어 붙이지 않아 SQL 주입을 막는다).
"""

import base64
import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from api.engine import safe_http
from nodes import NodeError

ROW_LIMIT = 500
TIMEOUT_SECONDS = 15
ENGINES = ("postgresql", "mysql")

_COMMENTS = re.compile(r"(--[^\n]*)|(/\*.*?\*/)", re.S)


def _one_statement(sql: str) -> str:
    s = _COMMENTS.sub(" ", sql or "").strip()
    s = s.rstrip(";").strip()
    if not s:
        raise NodeError("실행할 SQL이 비어 있어요. 조회할 문장을 적어 주세요.")
    if ";" in s:
        raise NodeError("SQL은 한 번에 한 문장만 실행할 수 있어요. 세미콜론(;)을 빼 주세요.")
    return s


def check_sql(sql: str, mode: str) -> str:
    s = _one_statement(sql)
    head = s.split(None, 1)[0].upper()
    if mode == "query" and head not in ("SELECT", "WITH"):
        raise NodeError(
            "조회 동작에는 SELECT 문만 쓸 수 있어요. 바꾸는 문장은 '실행' 동작을 쓰세요."
        )
    if mode == "execute" and head not in ("INSERT", "UPDATE", "DELETE"):
        raise NodeError(
            "실행 동작에는 INSERT·UPDATE·DELETE만 쓸 수 있어요(표 구조 변경은 막혀 있어요)."
        )
    if mode == "query" and re.search(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT)\b", s, re.I
    ):
        raise NodeError("조회 문장 안에 데이터를 바꾸는 명령이 있어요. 조회만 할 수 있어요.")
    return s


def check_host(host: str, port: int, allow_hosts: list[str]) -> None:
    host = (host or "").strip()
    if not host:
        raise NodeError("데이터베이스 주소(host)가 비어 있어요. 연결 정보를 확인하세요.")
    if not (1 <= int(port) <= 65535):
        raise NodeError("데이터베이스 포트가 올바르지 않아요. 연결 정보를 확인하세요.")
    if host.lower() in {h.strip().lower() for h in allow_hosts if h.strip()}:
        return
    try:
        safe_http.check_url(f"https://{host}:{int(port)}/")
    except NodeError as exc:
        raise NodeError(
            f"{exc.message} 사내 DB라면 관리자에게 '허용할 내부 주소'에 등록해 달라고 하세요."
        ) from None


def _plain(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime | date | time):
        return v.isoformat()
    if isinstance(v, bytes | bytearray | memoryview):
        return base64.b64encode(bytes(v)).decode()
    if isinstance(v, list | tuple):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    return v


def run_sql(
    *,
    engine: str,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    ssl: bool,
    sql: str,
    params: dict[str, Any] | None,
    mode: str,
    allow_hosts: list[str],
) -> dict[str, Any]:
    if engine not in ENGINES:
        raise NodeError("데이터베이스 종류는 postgresql 또는 mysql만 쓸 수 있어요.")
    stmt = check_sql(sql, mode)
    check_host(host, port, allow_hosts)
    args = {str(k): v for k, v in (params or {}).items()}
    try:
        if engine == "postgresql":
            return _pg(host, port, database, user, password, ssl, stmt, args, mode)
        return _mysql(host, port, database, user, password, ssl, stmt, args, mode)
    except NodeError:
        raise
    except Exception as exc:  # 드라이버 오류(연결 실패·문법 오류 등)
        msg = str(exc).replace(password, "****") if password else str(exc)
        raise NodeError(
            f"데이터베이스 작업이 실패했어요({type(exc).__name__}): {msg[:200]}",
            retryable=isinstance(exc, TimeoutError | ConnectionError),
        ) from None


def _rows(cur: Any) -> dict[str, Any]:
    rows = cur.fetchmany(ROW_LIMIT + 1)
    truncated = len(rows) > ROW_LIMIT
    rows = [_plain(dict(r)) for r in rows[:ROW_LIMIT]]
    return {"rows": rows, "count": len(rows), "truncated": truncated}


def _pg(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    ssl: bool,
    sql: str,
    params: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(
        host=host,
        port=int(port),
        dbname=database,
        user=user,
        password=password,
        connect_timeout=10,
        sslmode="require" if ssl else "prefer",
        options=f"-c statement_timeout={TIMEOUT_SECONDS * 1000}",
        row_factory=dict_row,
    ) as conn:
        if mode == "query":
            conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(sql, params or None)
            if mode == "query":
                return _rows(cur)
            affected = cur.rowcount
        conn.commit()
        return {"affected_rows": affected}


def _mysql(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    ssl: bool,
    sql: str,
    params: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    import pymysql
    import pymysql.cursors

    conn = pymysql.connect(
        host=host,
        port=int(port),
        user=user,
        password=password,
        database=database,
        connect_timeout=10,
        read_timeout=TIMEOUT_SECONDS,
        write_timeout=TIMEOUT_SECONDS,
        cursorclass=pymysql.cursors.DictCursor,
        ssl={"ssl": {}} if ssl else None,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            if mode == "query":
                cur.execute("SET SESSION TRANSACTION READ ONLY")
                cur.execute(f"SET SESSION MAX_EXECUTION_TIME={TIMEOUT_SECONDS * 1000}")
                cur.execute(sql, params or None)
                return _rows(cur)
            affected = cur.execute(sql, params or None)
        conn.commit()
        return {"affected_rows": int(affected)}
    finally:
        conn.close()
