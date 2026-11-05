"""MCP 클라이언트(v0.8, ADR 0012): 외부 MCP 서버의 도구를 흐름·에이전트에서 부른다.

Streamable HTTP 방식의 JSON-RPC 2.0만 쓴다(initialize → notifications/initialized →
tools/list · tools/call). 응답은 application/json 또는 text/event-stream 한 번의 답을 받는다.
네트워크는 모두 safe_http를 거친다(사설 IP·localhost 차단, 타임아웃, 응답 크기 제한).
토큰·주소는 연결 정보에만 두고, 이 모듈은 값을 기록하지 않는다.
"""

import contextlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from api.engine import safe_http
from nodes import NodeError

# 제니오가 요청하는 규격과, 서버가 돌려줘도 받아들이는 규격(협상)
REQUEST_PROTOCOL = "2025-06-18"
SUPPORTED_PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_TOOLS = 200
MAX_TOOL_PAGES = 10
MAX_TEXT = 20_000
MAX_SCHEMA_CHARS = 20_000
MAX_CONTENT_ITEMS = 50

RequestFn = Callable[..., dict[str, Any]]


@dataclass
class McpServer:
    """연결 정보에서 꺼낸 서버 주소와 인증 헤더."""

    url: str
    token: str = ""
    header_name: str = ""

    def headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        name = self.header_name.strip()
        if name:
            return {name: self.token}
        return {"Authorization": f"Bearer {self.token}"}


def server_from_secrets(secrets: dict[str, Any]) -> McpServer:
    url = str(secrets.get("url") or "").strip()
    if not url.lower().startswith(("https://", "http://")):
        raise NodeError(
            "MCP 서버 주소가 올바르지 않아요. 연결 정보에 https://로 시작하는 주소를 넣어 주세요."
        )
    return McpServer(
        url=url,
        token=str(secrets.get("token") or "").strip(),
        header_name=str(secrets.get("header_name") or "").strip(),
    )


class SessionExpiredError(Exception):
    pass


def _short(value: Any, limit: int) -> str:
    return " ".join(str(value).split())[:limit]


def parse_message(body: Any, rpc_id: int) -> dict[str, Any] | None:
    """응답 본문에서 요청 번호가 같은 JSON-RPC 메시지를 찾는다(JSON·배열·SSE 모두)."""
    candidates: list[Any] = []
    if isinstance(body, dict):
        candidates.append(body)
    elif isinstance(body, list):
        candidates.extend(body)
    elif isinstance(body, str):
        text = body.strip()
        if text.startswith(("{", "[")):
            try:
                loaded = json.loads(text)
                candidates.extend(loaded if isinstance(loaded, list) else [loaded])
            except json.JSONDecodeError:
                pass
        if not candidates:
            # text/event-stream: 빈 줄로 나뉜 이벤트의 data: 줄
            for block in text.replace("\r\n", "\n").split("\n\n"):
                data = "\n".join(
                    line[5:].lstrip() for line in block.split("\n") if line.startswith("data:")
                )
                if not data:
                    continue
                try:
                    candidates.append(json.loads(data))
                except json.JSONDecodeError:
                    continue
    for c in candidates:
        if isinstance(c, dict) and c.get("id") == rpc_id and ("result" in c or "error" in c):
            return c
    return None


class McpClient:
    def __init__(
        self,
        server: McpServer,
        *,
        request: RequestFn | None = None,
    ) -> None:
        self.server = server
        self._request: RequestFn = request or safe_http.request
        self.protocol: str | None = None
        self.session_id: str | None = None
        self.server_info: dict[str, Any] = {}
        self._next_id = 1
        self._ready = False

    # ---- 낮은 층 ----
    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json, text/event-stream", **self.server.headers()}
        if self.protocol:
            h["MCP-Protocol-Version"] = self.protocol
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        res = self._request("POST", self.server.url, headers=self._headers(), body=payload)
        status = int(res.get("status") or 0)
        hdrs = {str(k).lower(): v for k, v in (res.get("headers") or {}).items()}
        sid = hdrs.get("mcp-session-id")
        if sid:
            self.session_id = str(sid)[:200]
        if status in (401, 403):
            raise NodeError(
                "MCP 서버가 인증을 받아 주지 않았어요. 연결 정보의 토큰(헤더 이름)을 확인하세요."
            )
        if status == 404 and self.session_id:
            raise SessionExpiredError
        if status in (404, 405, 406, 415):
            raise NodeError(
                "이 주소는 MCP 서버(Streamable HTTP)가 아닌 것 같아요. 서버 설명서의 MCP 주소를 확인하세요."
            )
        if status >= 400:
            raise NodeError(
                f"MCP 서버가 오류로 답했어요(코드 {status}). 주소와 토큰을 확인한 뒤 다시 시도하세요."
            )
        return res

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        rpc_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
        if params is not None:
            payload["params"] = params
        res = self._post(payload)
        msg = parse_message(res.get("body"), rpc_id)
        if msg is None:
            raise NodeError(
                "MCP 서버의 답을 읽지 못했어요. 주소가 MCP 서버 주소인지 확인한 뒤 다시 시도하세요."
            )
        err = msg.get("error")
        if err is not None:
            detail = _short((err or {}).get("message") if isinstance(err, dict) else err, 200)
            raise NodeError(
                f"MCP 서버가 오류를 알려 줬어요: {detail or '이유 없음'}. 도구 이름과 넘긴 값을 확인하세요."
            )
        result = msg.get("result")
        return result if isinstance(result, dict) else {}

    def _notify(self, method: str) -> None:
        # 알림은 답이 없다(보통 202). 실패해도 이어 간다.
        with contextlib.suppress(SessionExpiredError):
            self._post({"jsonrpc": "2.0", "method": method})

    # ---- 높은 층 ----
    def initialize(self) -> None:
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": REQUEST_PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "genio", "version": "0.8"},
            },
        )
        version = str(result.get("protocolVersion") or "")
        if version not in SUPPORTED_PROTOCOLS:
            raise NodeError(
                f"MCP 서버의 규격 버전({version or '알 수 없음'})을 제니오가 쓸 수 없어요. 서버를 최신 버전으로 올리거나 관리자에게 문의하세요."
            )
        self.protocol = version
        info = result.get("serverInfo")
        self.server_info = info if isinstance(info, dict) else {}
        self._notify("notifications/initialized")
        self._ready = True

    def _ensure(self) -> None:
        if not self._ready:
            self.initialize()

    def _call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._ensure()
        try:
            return self._rpc(method, params)
        except SessionExpiredError:
            # 서버가 세션을 잊었다: 한 번만 새로 시작한다
            self._ready = False
            self.session_id = None
            self.protocol = None
            self._ensure()
            try:
                return self._rpc(method, params)
            except SessionExpiredError:
                raise NodeError(
                    "MCP 서버가 세션을 계속 끊어요. 잠시 후 다시 시도하세요.", retryable=True
                ) from None

    def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(MAX_TOOL_PAGES):
            result = self._call("tools/list", {"cursor": cursor} if cursor else {})
            for t in result.get("tools") or []:
                if isinstance(t, dict) and t.get("name"):
                    tools.append(normalize_tool(t))
                if len(tools) >= MAX_TOOLS:
                    return tools
            nxt = result.get("nextCursor")
            cursor = str(nxt) if isinstance(nxt, str) and nxt else None
            if cursor is None:
                break
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._call("tools/call", {"name": name, "arguments": arguments})
        return normalize_result(result)

    def close(self) -> None:
        """세션이 있으면 끝낸다(서버가 지원하지 않아도 괜찮다)."""
        if not self.session_id:
            return
        with contextlib.suppress(Exception):
            self._request("DELETE", self.server.url, headers=self._headers())
        self.session_id = None


def normalize_tool(t: dict[str, Any]) -> dict[str, Any]:
    schema = t.get("inputSchema")
    if (
        not isinstance(schema, dict)
        or len(json.dumps(schema, ensure_ascii=False)) > MAX_SCHEMA_CHARS
    ):
        schema = {"type": "object"}
    return {
        "name": str(t["name"])[:100],
        "description": _short(t.get("description") or t.get("title") or "", 500),
        "input_schema": schema,
    }


def normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    """tools/call 결과를 {text, content, structured, is_error}로 정리한다."""
    texts: list[str] = []
    items: list[dict[str, Any]] = []
    raw = result.get("content")
    for c in (raw if isinstance(raw, list) else [])[:MAX_CONTENT_ITEMS]:
        if not isinstance(c, dict):
            continue
        kind = str(c.get("type") or "")
        if kind == "text":
            text = str(c.get("text") or "")
            texts.append(text)
            items.append({"type": "text", "text": text[:MAX_TEXT]})
        elif kind in ("image", "audio"):
            items.append(
                {
                    "type": kind,
                    "mime": str(c.get("mimeType") or ""),
                    "note": f"{kind} 데이터 {len(str(c.get('data') or ''))}자(내용은 생략)",
                }
            )
        elif kind == "resource":
            raw_res = c.get("resource")
            res: dict[str, Any] = raw_res if isinstance(raw_res, dict) else {}
            text = str(res.get("text") or "")
            if text:
                texts.append(text)
            items.append(
                {"type": "resource", "uri": str(res.get("uri") or ""), "text": text[:MAX_TEXT]}
            )
        elif kind == "resource_link":
            items.append(
                {
                    "type": "resource_link",
                    "uri": str(c.get("uri") or ""),
                    "name": str(c.get("name") or ""),
                }
            )
        else:
            items.append({"type": kind or "unknown"})
    structured = result.get("structuredContent")
    structured = structured if isinstance(structured, dict) else None
    text = "\n".join(texts)
    if not text and structured is not None:
        text = json.dumps(structured, ensure_ascii=False)
    return {
        "text": text[:MAX_TEXT],
        "content": items,
        "structured": structured,
        "is_error": bool(result.get("isError")),
    }
