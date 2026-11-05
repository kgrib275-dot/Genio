"""공개 API 문서(v0.8): 밖에서 부를 수 있는 API만 골라 OpenAPI 문서로 내준다.

화면의 `/api-docs`가 이 문서를 읽어 방식·주소·매개변수·요청/응답 형태·curl 예시를 보여 준다.
관리·내부 경로(/workspaces, /auth, /admin 등)는 절대 담지 않는다. 로그인 없이 읽는다.
"""

import copy
from typing import Any

from fastapi import APIRouter, Request

from api.routers.common import public_origin

router = APIRouter(tags=["api-docs"])

# 밖에 문서로 내보낼 경로(앞부분 → 묶음 이름). 위에서부터 맞는 것을 쓴다.
GROUPS: tuple[tuple[str, str], ...] = (
    ("/api/v1/service/mcp", "MCP 서버"),
    ("/api/v1/service/", "서비스 API(앱 API 키)"),
    ("/api/v1/hooks/", "외부에서 받기(웹훅)"),
    ("/api/v1/public/apps/", "공유 링크 앱(챗·입력 폼)"),
)
# 문서에서 뺄 공개 경로(그림·미리보기·위젯 스크립트는 사람이 부를 API가 아님)
HIDDEN_PARTS = ("/share-image", "/share-logo", "/widget.js", "/public/share", "/og-default")
TAG_INFO = {
    "공유 링크 앱(챗·입력 폼)": "배포한 앱의 공유 주소(토큰)로 로그인 없이 부르는 API예요. 앱의 '쓸 수 있는 사람' 설정과 IP 제한을 따라요.",
    "서비스 API(앱 API 키)": "앱의 API 화면에서 만든 키(gk-로 시작)를 Authorization: Bearer <키> 헤더로 보내요. 키마다 권한 범위(대화·흐름 실행·기록 읽기·MCP)가 있어요.",
    "외부에서 받기(웹훅)": "앱의 자동 실행 화면에서 만든 비밀 주소로 호출해요. 서명 검증을 켰다면 서명 헤더도 보내요.",
    "MCP 서버": "앱을 MCP 도구로 공개해요. 키에 'MCP 도구' 권한이 있어야 하고, 앱의 'MCP로 게시'가 켜져 있어야 해요.",
}
SUMMARIES: dict[tuple[str, str], str] = {
    ("get", "/api/v1/public/apps/{token}"): "앱 정보(이름·입력 칸·기능)",
    ("post", "/api/v1/public/apps/{token}/chat"): "대화 보내기(SSE로 답을 받아요)",
    ("post", "/api/v1/public/apps/{token}/runs"): "흐름 한 번 실행(입력 폼)",
    ("get", "/api/v1/public/apps/{token}/runs/{run_id}"): "실행 결과 받기",
    ("get", "/api/v1/public/apps/{token}/sessions/{session_id}/messages"): "지난 대화 보기",
    ("get", "/api/v1/public/apps/{token}/sessions/{session_id}/state"): "대화 상태(상담원 연결 등)",
    ("post", "/api/v1/public/apps/{token}/sessions/{session_id}/handoff"): "상담원에게 넘기기",
    ("post", "/api/v1/public/apps/{token}/files"): "파일 올리기",
    ("post", "/api/v1/public/apps/{token}/messages/{message_id}/feedback"): "답변에 좋아요·싫어요",
    ("get", "/api/v1/service/parameters"): "앱 정보와 입력 칸",
    ("post", "/api/v1/service/chat-messages"): "대화 보내기",
    ("post", "/api/v1/service/workflows/run"): "흐름 실행하고 결과 받기",
    ("get", "/api/v1/service/runs/{run_id}"): "실행 결과 하나 보기",
    ("get", "/api/v1/service/runs"): "최근 실행 목록",
    ("post", "/api/v1/hooks/{token}"): "외부에서 받기(POST)",
    ("get", "/api/v1/hooks/{token}"): "외부에서 받기(GET)",
    ("post", "/api/v1/service/mcp"): "MCP 요청(JSON-RPC)",
}


def _group_of(path: str) -> str | None:
    if any(h in path for h in HIDDEN_PARTS):
        return None
    for prefix, name in GROUPS:
        if path.startswith(prefix):
            return name
    return None


def _refs(node: Any, found: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for v in node.values():
            _refs(v, found)
    elif isinstance(node, list):
        for v in node:
            _refs(v, found)


def build_public_openapi(full: dict[str, Any], origin: str) -> dict[str, Any]:
    """전체 OpenAPI에서 공개 경로만 뽑고, 쓰는 스키마만 남긴다."""
    paths: dict[str, Any] = {}
    for path, item in (full.get("paths") or {}).items():
        group = _group_of(path)
        if group is None:
            continue
        kept: dict[str, Any] = {}
        for method, op in item.items():
            if method not in ("get", "post", "put", "patch", "delete") or not isinstance(op, dict):
                continue
            op = copy.deepcopy(op)
            op["tags"] = [group]
            summary = SUMMARIES.get((method, path))
            if summary:
                op["summary"] = summary
            kept[method] = op
        if kept:
            paths[path] = kept
    used: set[str] = set()
    _refs(paths, used)
    schemas = (full.get("components") or {}).get("schemas") or {}
    keep: dict[str, Any] = {}
    todo = list(used)
    while todo:
        name = todo.pop()
        if name in keep or name not in schemas:
            continue
        keep[name] = copy.deepcopy(schemas[name])
        more: set[str] = set()
        _refs(schemas[name], more)
        todo.extend(more - set(keep))
    return {
        "openapi": full.get("openapi", "3.1.0"),
        "info": {
            "title": "제니오 공개 API",
            "version": str(full.get("info", {}).get("version", "1")),
            "description": "제니오 앱을 다른 시스템에서 부르는 API예요. 관리용 API는 담지 않았어요.",
        },
        "servers": [{"url": origin}],
        "tags": [{"name": n, "description": TAG_INFO.get(n, "")} for _, n in GROUPS][::-1],
        "paths": dict(sorted(paths.items())),
        "components": {"schemas": keep},
    }


@router.get("/openapi-public.json")
def openapi_public(request: Request) -> Any:
    """밖에서 부를 수 있는 API만 담은 OpenAPI 문서(공개 경로·서비스 API·웹훅·MCP)."""
    from fastapi.responses import JSONResponse

    doc = build_public_openapi(request.app.openapi(), public_origin(request))
    return JSONResponse(doc, headers={"Cache-Control": "public, max-age=300"})
