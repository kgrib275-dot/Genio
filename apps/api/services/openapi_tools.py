"""OpenAPI 3 명세 → 도구 목록(v0.8, ADR 0012).

붙여 넣은 글(JSON·YAML)이나 주소에서 읽은 명세를 업무 말로 쓸 수 있는 '도구(연산)' 목록으로 바꾼다.
- 명세 1MB 이하, 연산 200개 이하, 같은 문서 안의 $ref(#/...)만 풀어 준다(바깥 주소는 따라가지 않는다).
- 비밀값은 다루지 않는다(인증은 'HTTP 인증 정보' 연결 정보로 따로 고른다).
"""

import json
import re
from typing import Any

import yaml

from api.engine import safe_http
from nodes import NodeError

MAX_SPEC_BYTES = 1_000_000
MAX_OPERATIONS = 200
MAX_STORED_BYTES = 300_000
MAX_REF_DEPTH = 6
NODE_BUDGET = 200_000
METHODS = ("get", "post", "put", "patch", "delete")
PARAM_IN = ("path", "query", "header")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-\[\]]{1,64}$")
_SCHEMA_KEYS = ("type", "description", "enum", "format", "default", "nullable", "required")


class _Budget:
    def __init__(self) -> None:
        self.left = NODE_BUDGET

    def spend(self) -> None:
        self.left -= 1
        if self.left < 0:
            raise NodeError("명세가 너무 복잡해요. 필요한 부분만 남긴 명세로 다시 가져오세요.")


def _short(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def load_spec(text: str) -> dict[str, Any]:
    raw = text.strip()
    if not raw:
        raise NodeError(
            "가져올 명세가 비어 있어요. OpenAPI 명세(JSON 또는 YAML)를 붙여 넣어 주세요."
        )
    if len(raw.encode("utf-8")) > MAX_SPEC_BYTES:
        raise NodeError("명세가 너무 커요(최대 1MB). 필요한 부분만 남긴 명세를 쓰세요.")
    try:
        data = json.loads(raw) if raw.startswith("{") else yaml.safe_load(raw)
    except (json.JSONDecodeError, yaml.YAMLError):
        raise NodeError(
            "명세를 읽지 못했어요. JSON이나 YAML 형식이 맞는지 확인한 뒤 다시 시도하세요."
        ) from None
    if not isinstance(data, dict):
        raise NodeError("명세 모양이 맞지 않아요. OpenAPI 3 명세(openapi: 3.x)인지 확인하세요.")
    version = str(data.get("openapi") or "")
    if not version.startswith("3."):
        raise NodeError(
            "OpenAPI 3 명세만 가져올 수 있어요. 'openapi: 3.0.0' 같은 줄이 있는 명세를 쓰세요(Swagger 2는 변환이 필요해요)."
        )
    if not isinstance(data.get("paths"), dict) or not data["paths"]:
        raise NodeError("명세에 호출할 수 있는 주소(paths)가 없어요. 명세 내용을 확인하세요.")
    return data


def fetch_spec(url: str) -> str:
    """명세 주소를 safe_http로 읽는다(사설망 차단, 1MB 제한)."""
    target = url.strip()
    if not target.lower().startswith(("https://", "http://")):
        raise NodeError("명세 주소는 https://로 시작해야 해요. 주소를 다시 확인하세요.")
    res = safe_http.request(
        "GET", target, headers={"Accept": "application/json, application/yaml, */*"}
    )
    if int(res.get("status") or 0) >= 400:
        raise NodeError(
            f"명세 주소에서 파일을 받지 못했어요(코드 {res.get('status')}). 주소를 확인하세요."
        )
    body = res.get("body")
    return body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)


def _pointer(spec: dict[str, Any], ref: str) -> Any:
    node: Any = spec
    for part in ref[2:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return None
    return node


def _deref(node: Any, spec: dict[str, Any], budget: _Budget, depth: int = 0) -> Any:
    """같은 문서의 $ref를 풀어 준다. 깊거나 바깥 참조면 빈 객체로 바꾼다."""
    budget.spend()
    if isinstance(node, dict) and "$ref" in node:
        ref = str(node["$ref"])
        if not ref.startswith("#/") or depth >= MAX_REF_DEPTH:
            return {}
        target = _pointer(spec, ref)
        return _deref(target, spec, budget, depth + 1) if target is not None else {}
    return node


def _schema(node: Any, spec: dict[str, Any], budget: _Budget, depth: int = 0) -> dict[str, Any]:
    """도구 입력 칸을 만들 만큼만 남긴 간단한 스키마."""
    node = _deref(node, spec, budget, depth)
    if not isinstance(node, dict):
        return {}
    out: dict[str, Any] = {}
    for key in _SCHEMA_KEYS:
        if key in node:
            out[key] = node[key]
    if "description" in out:
        out["description"] = _short(out["description"], 300)
    if isinstance(out.get("enum"), list):
        out["enum"] = out["enum"][:50]
    if isinstance(out.get("required"), list):
        out["required"] = [str(r) for r in out["required"]][:50]
    for combo in ("allOf",):  # 합치기만 지원한다
        parts = node.get(combo)
        if isinstance(parts, list):
            props: dict[str, Any] = {}
            req: list[str] = []
            for p in parts[:10]:
                sub = _schema(p, spec, budget, depth + 1)
                props.update(sub.get("properties") or {})
                req.extend(sub.get("required") or [])
            if props:
                out.setdefault("type", "object")
                out["properties"] = {**(out.get("properties") or {}), **props}
                out["required"] = sorted({*out.get("required", []), *req})
    props_in = node.get("properties")
    if isinstance(props_in, dict) and depth < MAX_REF_DEPTH:
        out["properties"] = {
            str(k)[:64]: _schema(v, spec, budget, depth + 1) for k, v in list(props_in.items())[:60]
        }
        out.setdefault("type", "object")
    items = node.get("items")
    if items is not None and depth < MAX_REF_DEPTH:
        out["items"] = _schema(items, spec, budget, depth + 1)
        out.setdefault("type", "array")
    return out


def _parameters(
    path_item: dict[str, Any], op: dict[str, Any], spec: dict[str, Any], budget: _Budget
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in [*(path_item.get("parameters") or []), *(op.get("parameters") or [])]:
        p = _deref(raw, spec, budget)
        if not isinstance(p, dict):
            continue
        name, where = str(p.get("name") or ""), str(p.get("in") or "")
        if where not in PARAM_IN or not _NAME_RE.match(name):
            continue
        sch = _schema(p.get("schema") or {}, spec, budget)
        merged[(where, name)] = {
            "name": name,
            "in": where,
            "required": bool(p.get("required")) or where == "path",
            "description": _short(p.get("description"), 200),
            "type": str(sch.get("type") or "string"),
            "enum": sch.get("enum"),
            "default": sch.get("default"),
        }
    return list(merged.values())[:60]


def _body(
    op: dict[str, Any], spec: dict[str, Any], budget: _Budget
) -> tuple[dict[str, Any] | None, bool]:
    rb = _deref(op.get("requestBody"), spec, budget)
    if not isinstance(rb, dict):
        return None, False
    content = rb.get("content")
    if not isinstance(content, dict):
        return None, False
    for mime, media in content.items():
        if str(mime).lower() == "application/json" or str(mime).lower().endswith("+json"):
            schema = _schema((media or {}).get("schema") or {}, spec, budget)
            return schema or {"type": "object"}, bool(rb.get("required"))
    return None, False


def _op_id(method: str, path: str, raw: Any, seen: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_]", "_", str(raw)) if raw else ""
    if not base:
        base = method + "_" + re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_")
    base = base[:60] or method
    name, n = base, 2
    while name in seen:
        name = f"{base}_{n}"
        n += 1
    seen.add(name)
    return name


def _base_url(spec: dict[str, Any]) -> str:
    servers = spec.get("servers")
    if not isinstance(servers, list) or not servers or not isinstance(servers[0], dict):
        return ""
    url = str(servers[0].get("url") or "")
    for name, var in (servers[0].get("variables") or {}).items():
        if isinstance(var, dict):
            url = url.replace("{" + str(name) + "}", str(var.get("default") or ""))
    return url.strip().rstrip("/")


def parse_operations(spec: dict[str, Any]) -> dict[str, Any]:
    """명세 → {title, version, base_url, operations, total, truncated}."""
    budget = _Budget()
    ops: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for path, item in spec["paths"].items():
        if not isinstance(item, dict) or not str(path).startswith("/"):
            continue
        for method in METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            total += 1
            if len(ops) >= MAX_OPERATIONS:
                continue
            body, body_required = _body(op, spec, budget)
            ops.append(
                {
                    "id": _op_id(method, str(path), op.get("operationId"), seen),
                    "method": method.upper(),
                    "path": str(path),
                    "summary": _short(op.get("summary") or op.get("description"), 200),
                    "parameters": _parameters(item, op, spec, budget),
                    "body_schema": body,
                    "body_required": body_required,
                }
            )
    raw_info = spec.get("info")
    info: dict[str, Any] = raw_info if isinstance(raw_info, dict) else {}
    return {
        "title": _short(info.get("title"), 100),
        "version": _short(info.get("version"), 40),
        "base_url": _base_url(spec),
        "operations": ops,
        "total": total,
        "truncated": total > len(ops),
    }


def preview(*, url: str | None, text: str | None) -> dict[str, Any]:
    if bool(url) == bool(text):
        raise NodeError("명세 주소나 명세 글 중 하나만 넣어 주세요.")
    raw = fetch_spec(str(url)) if url else str(text)
    return parse_operations(load_spec(raw))


def pick(parsed: dict[str, Any], selected: list[str] | None) -> list[dict[str, Any]]:
    """고른 연산만 남긴다(비어 있으면 모두). 저장 크기도 확인한다."""
    ops: list[dict[str, Any]] = parsed["operations"]
    if selected:
        wanted = set(selected)
        ops = [o for o in ops if o["id"] in wanted]
    if not ops:
        raise NodeError("가져올 도구를 하나 이상 골라 주세요.")
    if len(json.dumps(ops, ensure_ascii=False).encode("utf-8")) > MAX_STORED_BYTES:
        raise NodeError(
            "고른 도구가 너무 많거나 커요. 도구를 줄여서 다시 가져오세요(필요한 것만 고르면 돼요)."
        )
    return ops
