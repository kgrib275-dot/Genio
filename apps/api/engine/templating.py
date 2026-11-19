"""템플릿(`{{nodeId.field}}`, Jinja2 샌드박스)과 조건식(simpleeval)."""

import json
import re
from collections.abc import Iterator
from typing import Any

from jinja2 import ChainableUndefined, Undefined
from jinja2.exceptions import SecurityError, TemplateError
from jinja2.sandbox import SandboxedEnvironment
from simpleeval import EvalWithCompoundTypes

REF_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)((?:\.[A-Za-z0-9_]+)*)\s*\}\}")
SINGLE_REF_RE = re.compile(r"^\s*\{\{\s*([A-Za-z_][A-Za-z0-9_]*)((?:\.[A-Za-z0-9_]+)*)\s*\}\}\s*$")


def _finalize(value: Any) -> Any:
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    if value is None or isinstance(value, Undefined):
        return ""
    return value


MAX_RENDER_CHARS = 1_000_000  # 문장 틀 결과 길이 한도
_MAX_SEQ = 200_000  # 'a' * 큰수 같은 곱셈으로 만들 수 있는 길이 한도


class _LimitedEnvironment(SandboxedEnvironment):
    """곱셈·거듭제곱을 가로채 터무니없이 큰 값을 만들지 못하게 한다(시간·메모리 폭주 방지)."""

    intercepted_binops = frozenset({"*", "**"})

    def call_binop(self, context: Any, operator: str, left: Any, right: Any) -> Any:
        if operator == "*":
            for seq, n in ((left, right), (right, left)):
                if (
                    isinstance(seq, str | bytes | list | tuple)
                    and isinstance(n, int)
                    and len(seq) * max(n, 0) > _MAX_SEQ
                ):
                    raise SecurityError("반복해서 만드는 글이 너무 길어요.")
        if (
            operator == "**"
            and isinstance(left, int)
            and isinstance(right, int)
            and abs(left).bit_length() * max(right, 0) > 100_000
        ):
            raise SecurityError("거듭제곱 값이 너무 커요.")
        return super().call_binop(context, operator, left, right)


_env = _LimitedEnvironment(autoescape=False, finalize=_finalize, undefined=ChainableUndefined)


class TemplateRenderError(Exception):
    pass


def render(template: str, scope: dict[str, Any]) -> str:
    if "{{" not in template and "{%" not in template:
        return template
    try:
        out: list[str] = []
        size = 0
        for chunk in _env.from_string(template).generate(scope):
            size += len(chunk)
            if size > MAX_RENDER_CHARS:
                raise TemplateRenderError("문장 틀의 결과가 너무 길어요. 반복을 줄여 주세요.")
            out.append(chunk)
        return "".join(out)
    except TemplateError as exc:
        raise TemplateRenderError(f"문장 틀을 채우지 못했어요: {exc.message}") from exc


def lookup(scope: dict[str, Any], path: str) -> Any:
    cur: Any = scope
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def render_value(value: Any, scope: dict[str, Any]) -> Any:
    """dict/list를 재귀로 채운다. 문자열 전체가 참조 하나면 원래 값(객체 등)을 그대로 넘긴다."""
    if isinstance(value, str):
        m = SINGLE_REF_RE.match(value)
        if m:
            return lookup(scope, m.group(1) + m.group(2))
        return render(value, scope)
    if isinstance(value, dict):
        return {k: render_value(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, scope) for v in value]
    return value


_SAFE_FUNCS = {
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "lower": lambda s: str(s).lower(),
    "upper": lambda s: str(s).upper(),
    "contains": lambda a, b: str(b) in str(a),
}


def evaluate(expr: str, scope: dict[str, Any]) -> Any:
    """`{{n2.category}} == 'billing'` 같은 조건식을 안전하게 계산한다."""
    refs: dict[str, Any] = {}

    def _sub(m: re.Match[str]) -> str:
        name = f"__ref{len(refs)}"
        refs[name] = lookup(scope, m.group(1) + m.group(2))
        return name

    py_expr = REF_RE.sub(_sub, expr)
    evaluator = EvalWithCompoundTypes(names=refs, functions=_SAFE_FUNCS)
    return evaluator.eval(py_expr)


def iter_refs(value: Any) -> Iterator[tuple[str, str]]:
    """data 안의 모든 `{{node.field...}}` 참조를 (node_id, 첫 필드) 쌍으로 돌려준다."""
    if isinstance(value, str):
        for m in REF_RE.finditer(value):
            path = m.group(2).lstrip(".")
            yield m.group(1), path.split(".")[0] if path else ""
    elif isinstance(value, dict):
        for v in value.values():
            yield from iter_refs(v)
    elif isinstance(value, list):
        for v in value:
            yield from iter_refs(v)
