"""Dify 앱 가져오기(v0.8, ADR 0012): Dify DSL(YAML)을 제니오 앱(흐름·앱 기능·환경 값)으로 바꾼다.

- `convert(text)`는 DB를 쓰지 않는 순수 변환이다. 옮기지 못한 단계는 '꺼 둔 자리 표시 단계'로 남겨
  흐름 모양을 보이게 하고, 무엇이 바뀌었는지 변환 보고서(report)에 적는다.
- DSL은 `yaml.safe_load`(별칭 금지)로만 읽는다. 파일은 2MB 이하.
- Dify 변수 참조 `{{#노드.값#}}`·`value_selector: [노드, 값]`을 제니오의 `{{노드.값}}`으로 바꾼다.
  제니오 단계가 내놓는 값 이름이 다른 곳(예: 지식 검색 `result` → `context`)은 이름도 함께 바꾼다.
- 가져온 앱은 늘 '초안'이고, 변환이 끝난 흐름은 검증기를 한 번 돌려 남은 문제를 보고서에 적는다.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from api.core.errors import AppError

MAX_BYTES = 2 * 1024 * 1024
MAX_NODES = 300
SUPPORTED_MODES = ("workflow", "advanced-chat", "chat", "agent-chat", "completion")
CHILD_TYPES = ("llm", "template", "http", "code", "knowledge_search", "parameter_extractor")
SELECTOR_RE = re.compile(r"\{\{#([^#{}]+?)#\}\}")
KEY_RE = re.compile(r"[^A-Za-z0-9_]")

# 제니오 단계가 내놓는 값 이름(Dify 값 이름 → 제니오 값 이름)
FIELD_MAP: dict[str, dict[str, str]] = {
    "knowledge-retrieval": {"result": "context"},
    "http-request": {"status_code": "status"},
    "list-operator": {"first_record": "first", "last_record": "result"},
    "iteration": {"output": "results"},
    "loop": {},
}
# Dify에만 있는 시스템 값 중 제니오가 대신하는 것 / 없는 것
SYS_UNSUPPORTED = (
    "user_id",
    "conversation_id",
    "dialogue_count",
    "app_id",
    "workflow_id",
    "workflow_run_id",
    "timestamp",
)


class _NoAliasLoader(yaml.SafeLoader):  # type: ignore[misc]
    """YAML 별칭(*a)을 막는다(작은 파일이 크게 부풀려지는 공격 방지)."""

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.events.AliasEvent):
            raise yaml.YAMLError("alias")
        return super().compose_node(parent, index)


@dataclass
class Report:
    mode: str = ""
    dify_version: str = ""
    converted: list[dict[str, str]] = field(default_factory=list)
    needs_attention: list[dict[str, str]] = field(default_factory=list)
    unsupported: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    validation_errors: list[dict[str, str]] = field(default_factory=list)

    def dump(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "dify_version": self.dify_version,
            "converted": self.converted,
            "needs_attention": self.needs_attention,
            "unsupported": self.unsupported,
            "warnings": self.warnings,
            "validation_errors": self.validation_errors,
            "stats": {
                "converted": len(self.converted),
                "needs_attention": len(self.needs_attention),
                "unsupported": len(self.unsupported),
                "validation_errors": len(self.validation_errors),
            },
        }


@dataclass
class Converted:
    name: str
    description: str
    icon: str
    app_type: str
    graph: dict[str, Any]
    features: dict[str, Any]
    env_vars: list[dict[str, Any]]
    report: Report


# ---------------- 읽기 ----------------
def parse_text(raw: bytes | str) -> dict[str, Any]:
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    if len(data) > MAX_BYTES:
        raise AppError(
            413, "파일이 너무 커요(최대 2MB).", "Dify에서 내보낸 앱 파일(.yml)만 올려 주세요."
        )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise AppError(
            422, "파일의 글자 모양을 읽지 못했어요.", "UTF-8로 저장된 .yml 파일을 올려 주세요."
        ) from None
    try:
        doc = yaml.load(text, Loader=_NoAliasLoader)  # noqa: S506 - SafeLoader를 바탕으로 한 안전 로더
    except (yaml.YAMLError, RecursionError, ValueError):
        raise AppError(
            422,
            "파일을 읽지 못했어요. YAML 형식이 올바르지 않아요.",
            "Dify에서 '앱 > 내보내기(DSL)'로 받은 .yml 파일을 그대로 올려 주세요.",
        ) from None
    if not isinstance(doc, dict):
        raise _not_dify()
    return doc


def _not_dify() -> AppError:
    return AppError(
        422,
        "Dify에서 내보낸 앱 파일이 아니에요.",
        "Dify의 앱 화면에서 '내보내기(DSL)'로 받은 .yml 파일인지 확인하세요.",
    )


def _as_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def _s(v: Any) -> str:
    return "" if v is None else str(v)


def _key(name: str, fallback: str = "value") -> str:
    k = KEY_RE.sub("_", name or "").strip("_") or fallback
    return k if re.match(r"[A-Za-z_]", k) else f"v_{k}"


def _plain_text(text: str) -> str:
    """Dify 메모 글이 Lexical JSON이면 글자만 꺼낸다."""
    t = text.strip()
    if not t.startswith("{"):
        return text
    try:
        root = json.loads(t).get("root", {})
    except (ValueError, AttributeError):
        return text
    lines: list[str] = []

    def walk(n: Any) -> str:
        if not isinstance(n, dict):
            return ""
        if "text" in n:
            return _s(n["text"])
        return "".join(walk(c) for c in _as_list(n.get("children")))

    for para in _as_list(root.get("children")):
        lines.append(walk(para))
    return "\n".join(lines).strip() or text


# ---------------- 변환기 ----------------
class _Converter:
    def __init__(self, doc: dict[str, Any]) -> None:
        self.doc = doc
        self.report = Report()
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.notes: list[dict[str, Any]] = []
        self.ids: dict[str, str] = {}  # Dify id → 제니오 id
        self.types: dict[str, str] = {}  # Dify id → Dify 단계 종류
        self.start_id = ""
        self.start_vars: dict[str, str] = {}  # Dify 시작 값 이름 → 제니오 입력 항목 키
        self.chat = False
        self.counter = 1
        self.iter_scope: dict[str, str] = {}  # 반복·되풀이 Dify id → 'iteration'|'loop'
        self.ctx_ref = ""  # AI 단계의 '{{#context#}}' 자리에 넣을 값(지식 검색 결과)
        self.in_scope: str = ""  # 지금 바꾸는 하위 동작이 속한 반복·되풀이 Dify id
        self.branch_maps: dict[
            str, dict[str, str]
        ] = {}  # 제니오 갈림길 id → {Dify 출구: 제니오 출구}

    # ---- 보고 ----
    def warn(self, msg: str) -> None:
        if msg not in self.report.warnings:
            self.report.warnings.append(msg)

    def attention(self, node: str, label: str, msg: str) -> None:
        self.report.needs_attention.append({"node": node, "label": label, "message": msg})

    # ---- 값 참조 ----
    def new_id(self) -> str:
        self.counter += 1
        return f"n{self.counter}"

    def input_node(self) -> dict[str, Any] | None:
        return next((n for n in self.nodes if n["type"] == "input"), None)

    def file_key(self) -> str:
        """시작 단계의 파일 항목 키(없으면 만든다)."""
        node = self.input_node()
        if node is None:
            return "files"
        fields = node["data"]["fields"]
        found = next((f for f in fields if f.get("type") == "file"), None)
        if found is None:
            found = {"key": "files", "label": "파일", "type": "file", "required": False}
            fields.append(found)
        return str(found["key"])

    def ref(self, selector: Any) -> str:
        """Dify 값 선택자 → 제니오 `{{노드.값}}`. 바꿀 수 없으면 빈 글자와 알림."""
        parts = [_s(p) for p in _as_list(selector) if _s(p)]
        if len(parts) < 2:
            return ""
        head, rest = parts[0], parts[1:]
        if head == "sys":
            return self._sys(rest[0])
        if head == "env":
            return f"{{{{env.{_key(rest[0])}}}}}"
        if head == "conversation":
            return f"{{{{conv.{_key(rest[0])}}}}}"
        if self.in_scope and head == self.in_scope:
            kind = self.iter_scope.get(head, "iteration")
            if rest[0] == "item" and kind == "iteration":
                return "{{item}}"
            if rest[0] == "index":
                return "{{index}}" if kind == "iteration" else "{{loop.index}}"
            if kind == "loop":
                return "{{loop.last}}"
        gid = self.ids.get(head)
        if gid is None:
            self.warn(f"없는 단계 '{head}'의 값을 쓰는 곳이 있어 빈 값으로 바꿨어요.")
            return ""
        if head == self.start_id:
            name = self.start_vars.get(rest[0], _key(rest[0]))
            return "{{" + ".".join([gid, name, *[_key(p) for p in rest[1:]]]) + "}}"
        dtype = self.types.get(head, "")
        first = FIELD_MAP.get(dtype, {}).get(rest[0], rest[0])
        if dtype == "tool":
            first = "output"
        return "{{" + ".".join([gid, _key(first), *[_key(p) for p in rest[1:]]]) + "}}"

    def _sys(self, name: str) -> str:
        if name == "query":
            if self.input_node() is None:
                return ""
            return "{{n1.message}}" if self.chat else ""
        if name == "files":
            return "{{n1." + self.file_key() + "}}"
        if name in SYS_UNSUPPORTED:
            self.warn(f"시스템 값 'sys.{name}'은 제니오에 없어 빈 값으로 바꿨어요.")
            return ""
        self.warn(f"알 수 없는 시스템 값 'sys.{name}'을 빈 값으로 바꿨어요.")
        return ""

    def text(self, value: Any) -> str:
        """글 안의 `{{#노드.값#}}`을 제니오 참조로 바꾼다."""
        s = _s(value)
        return SELECTOR_RE.sub(
            lambda m: self.ctx_ref if m.group(1) == "context" else self.ref(m.group(1).split(".")),
            s,
        )

    def value_of(self, v: Any) -> str:
        """Dify 에이전트 값 {type: constant|variable|mixed, value} 등을 글로."""
        if isinstance(v, dict) and "value" in v:
            if v.get("type") == "variable":
                return self.ref(v["value"])
            return self.text(v["value"])
        return self.text(v)

    # ---- 단계 만들기 ----
    def add_node(
        self,
        dify: dict[str, Any],
        gtype: str,
        data: dict[str, Any],
        *,
        disabled: bool = False,
        gid: str | None = None,
    ) -> str:
        did = _s(dify.get("id"))
        node_id = gid or self.ids.get(did) or self.new_id()
        self.ids[did] = node_id
        title = _s(_as_dict(dify.get("data")).get("title")) or gtype
        data = {"label": title[:60], **data}
        desc = _s(_as_dict(dify.get("data")).get("desc")).strip()
        if desc and "note" not in data:
            data["note"] = desc[:300]
        pos = _as_dict(dify.get("position"))
        node: dict[str, Any] = {
            "id": node_id,
            "type": gtype,
            "position": {"x": float(pos.get("x") or 0), "y": float(pos.get("y") or 0)},
            "data": data,
        }
        if disabled:
            node["disabled"] = True
        self.nodes.append(node)
        return node_id

    def placeholder(self, dify: dict[str, Any], dtype: str, why: str) -> None:
        d = _as_dict(dify.get("data"))
        title = _s(d.get("title")) or dtype
        msg = f"Dify '{dtype}' 단계는 아직 지원하지 않아요. {why}".strip()
        gid = self.add_node(
            dify, "template", {"template": f"({msg})", "note": msg[:300]}, disabled=True
        )
        self.report.unsupported.append(
            {"node": gid, "label": title, "dify_type": dtype, "message": msg}
        )

    def done(self, gid: str, dify: dict[str, Any], dtype: str, gtype: str) -> None:
        d = _as_dict(dify.get("data"))
        self.report.converted.append(
            {
                "node": gid,
                "label": _s(d.get("title")) or dtype,
                "dify_type": dtype,
                "genio_type": gtype,
            }
        )

    def model_note(self, data: dict[str, Any]) -> str:
        m = _as_dict(data.get("model"))
        name = _s(m.get("name"))
        prov = _s(m.get("provider")).split("/")[-1]
        return f"원래 모델: {prov} {name}".strip() if name else ""

    # ---- 단계 종류별 변환 ----
    def convert_node(self, dify: dict[str, Any]) -> None:
        d = _as_dict(dify.get("data"))
        dtype = _s(d.get("type"))
        did = _s(dify.get("id"))
        self.types[did] = dtype
        handler = getattr(self, "_n_" + dtype.replace("-", "_"), None)
        if handler is None:
            what = "시작 단계가 달라서" if dtype.startswith("trigger") else ""
            self.placeholder(dify, dtype or "알 수 없음", what)
            return
        handler(dify, d)

    def _n_start(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        if self.start_id:
            self.placeholder(dify, "start", "시작 단계는 하나만 둘 수 있어요.")
            return
        self.start_id = _s(dify.get("id"))
        fields: list[dict[str, Any]] = []
        used: set[str] = set()
        if self.chat:
            fields.append({"key": "message", "label": "질문", "type": "text", "required": True})
            used.add("message")
        for v in _as_list(d.get("variables")):
            v = _as_dict(v)
            name = _s(v.get("variable"))
            if not name:
                continue
            k = _key(name)
            base = k
            n = 1
            while k in used:
                k = f"{base}_{n}"
                n += 1
            used.add(k)
            self.start_vars[name] = k
            vtype = _s(v.get("type"))
            label = _s(v.get("label")) or name
            ftype = {"number": "number", "checkbox": "boolean"}.get(vtype, "text")
            if vtype in ("file", "file-list"):
                ftype = "file"
            if vtype == "select":
                opts = ", ".join(_s(o) for o in _as_list(v.get("options")))
                label = f"{label} (선택: {opts})" if opts else label
            if vtype == "json_object":
                self.warn(f"'{name}' 값(JSON)은 글 입력칸으로 바꿨어요.")
            fields.append(
                {"key": k, "label": label[:60], "type": ftype, "required": bool(v.get("required"))}
            )
        if not fields:
            fields.append({"key": "message", "label": "입력", "type": "text", "required": False})
        gid = self.add_node({**dify, "id": self.start_id}, "input", {"fields": fields}, gid="n1")
        self.done(gid, dify, "start", "input")

    def _n_end(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        outs = [_as_dict(o) for o in _as_list(d.get("outputs"))]
        lines: list[str] = []
        for o in outs:
            r = self.ref(o.get("value_selector"))
            if r:
                lines.append(r if len(outs) == 1 else f"{_s(o.get('variable'))}: {r}")
        gid = self.add_node(dify, "output", {"template": "\n".join(lines) or "완료"})
        self.done(gid, dify, "end", "output")

    def _n_answer(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        gid = self.add_node(dify, "output", {"template": self.text(d.get("answer")) or "완료"})
        self.done(gid, dify, "answer", "output")

    def _llm_data(self, d: dict[str, Any]) -> dict[str, Any]:
        ctx = _as_dict(d.get("context"))
        self.ctx_ref = self.ref(ctx.get("variable_selector")) if ctx.get("enabled") else ""
        tpl = d.get("prompt_template")
        msgs = [_as_dict(m) for m in tpl] if isinstance(tpl, list) else [_as_dict(tpl)]
        system: list[str] = []
        user: list[str] = []
        for m in msgs:
            role = _s(m.get("role")) or "user"
            t = self.text(m.get("text"))
            if not t:
                continue
            if role == "system":
                system.append(t)
            elif role == "assistant":
                user.append(f"[예시 답변]\n{t}")
            else:
                user.append(t)
        prompt = "\n\n".join(user)
        mem = d.get("memory")
        if not prompt:
            q = _s(_as_dict(mem).get("query_prompt_template"))
            prompt = self.text(q) or ("{{n1.message}}" if self.chat else "위 지시대로 해 주세요.")
        data: dict[str, Any] = {"provider": "default", "prompt": prompt}
        if system:
            data["system"] = "\n\n".join(system)
        temp = _as_dict(_as_dict(d.get("model")).get("completion_params")).get("temperature")
        if isinstance(temp, int | float) and 0 <= temp <= 2:
            data["temperature"] = float(temp)
        if isinstance(mem, dict) and self.chat:
            data["memory"] = True
        vision = _as_dict(d.get("vision"))
        if vision.get("enabled"):
            sel = _as_dict(vision.get("configs")).get("variable_selector") or ["sys", "files"]
            r = self.ref(sel)
            if r:
                data["images"] = [r]
        if d.get("structured_output_enabled"):
            self.warn(
                "AI 단계의 '구조화 출력'은 옮기지 못했어요. 필요하면 출력 형식을 다시 정해 주세요."
            )
        note = self.model_note(d)
        if note:
            data["note"] = note
        self.ctx_ref = ""
        return data

    def _n_llm(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        data = self._llm_data(d)
        gid = self.add_node(dify, "llm", data)
        note = self.model_note(d)
        if note:
            self.attention(
                gid,
                _s(d.get("title")) or "AI 답변",
                f"{note}. 관리 > AI 모델에서 쓸 모델을 고르거나 이 단계의 '모델'을 정해 주세요.",
            )
        self.done(gid, dify, "llm", "llm")

    def _n_knowledge_retrieval(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        q = self.ref(d.get("query_variable_selector")) or ("{{n1.message}}" if self.chat else "")
        data: dict[str, Any] = {"kb_id": "", "query": q}
        multi = _as_dict(d.get("multiple_retrieval_config"))
        top_k = multi.get("top_k")
        if isinstance(top_k, int) and 1 <= top_k <= 20:
            data["top_k"] = top_k
        thr = multi.get("score_threshold")
        if multi.get("score_threshold_enabled") and isinstance(thr, int | float) and 0 <= thr <= 1:
            data["score_threshold"] = float(thr)
        gid = self.add_node(dify, "knowledge_search", data)
        n = len(_as_list(d.get("dataset_ids")))
        self.attention(
            gid,
            _s(d.get("title")) or "지식 검색",
            f"Dify 지식베이스 {n}개는 옮겨지지 않아요. 지식베이스에 같은 문서를 올리고 이 단계에서 골라 주세요."
            if n
            else "지식베이스를 골라 주세요.",
        )
        self.done(gid, dify, "knowledge-retrieval", "knowledge_search")

    # 비교 연산자 → 제니오 조건식
    def _cond(self, c: dict[str, Any]) -> str:
        left = self.ref(c.get("variable_selector")) or "''"
        op = _s(c.get("comparison_operator"))
        raw = c.get("value")
        is_num = _s(c.get("varType") or c.get("numberVarType")) == "number" or op in (
            "=",
            "≠",
            ">",
            "<",
            "≥",
            "≤",
        )

        def val() -> str:
            s = self.text(raw)
            if SELECTOR_RE.search(_s(raw)) and re.fullmatch(r"\{\{[^{}]+\}\}", s.strip()):
                return s.strip()
            if is_num:
                try:
                    float(s)
                    return s
                except ValueError:
                    pass
            return repr(s)

        if op in ("contains",):
            return f"contains({left}, {val()})"
        if op == "not contains":
            return f"not contains({left}, {val()})"
        if op == "start with":
            lit = self.text(raw)
            return f"str({left})[:{len(lit)}] == {lit!r}"
        if op == "end with":
            lit = self.text(raw)
            return f"str({left})[-{max(len(lit), 1)}:] == {lit!r}"
        if op in ("is", "="):
            return f"{left} == {val()}"
        if op in ("is not", "≠"):
            return f"{left} != {val()}"
        if op in (">", "<"):
            return f"{left} {op} {val()}"
        if op == "≥":
            return f"{left} >= {val()}"
        if op == "≤":
            return f"{left} <= {val()}"
        if op in ("empty", "null"):
            return f"not {left}"
        if op in ("not empty", "not null", "exists"):
            return f"bool({left})"
        if op == "not exists":
            return f"not {left}"
        if op == "in":
            return f"{left} in {val()}"
        if op == "not in":
            return f"{left} not in {val()}"
        self.warn(f"조건 연산자 '{op}'는 옮기지 못해 '항상 아님'으로 바꿨어요.")
        return "1 == 0"

    def _n_if_else(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        cases: list[dict[str, str]] = []
        handles: dict[str, str] = {}
        used: set[str] = {"else"}
        for i, c in enumerate(_as_list(d.get("cases"))):
            c = _as_dict(c)
            cid = _s(c.get("case_id") or c.get("id")) or f"case{i + 1}"
            gh = cid if cid not in used else f"case{i + 1}"
            used.add(gh)
            handles[cid] = gh
            parts = [self._cond(_as_dict(x)) for x in _as_list(c.get("conditions"))]
            joiner = " or " if _s(c.get("logical_operator")) == "or" else " and "
            expr = (
                joiner.join(f"({p})" for p in parts)
                if len(parts) > 1
                else (parts[0] if parts else "1 == 1")
            )
            cases.append({"id": gh, "when": expr})
        handles["false"] = "else"
        gid = self.add_node(
            dify,
            "condition",
            {"cases": cases or [{"id": "case1", "when": "1 == 1"}], "else": "else"},
        )
        self.branch_maps[gid] = handles
        self.done(gid, dify, "if-else", "condition")

    def _n_code(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        lang = _s(d.get("code_language")) or "python3"
        code = _s(d.get("code"))
        variables = [_as_dict(v) for v in _as_list(d.get("variables"))]
        inputs = {
            _key(_s(v.get("variable"))): self.ref(v.get("value_selector"))
            for v in variables
            if v.get("variable")
        }
        names = [_key(_s(v.get("variable"))) for v in variables if v.get("variable")]
        if lang == "javascript":
            if re.search(r"function\s+main\s*\(\s*\{", code):
                call = "return main(inputs);"
            else:
                call = "return main(" + ", ".join(f"inputs.{n}" for n in names) + ");"
            body = f"{code}\n\n{call}"
            glang = "javascript"
        else:
            call = "result = main(" + ", ".join(f"{n}=inputs.get({n!r})" for n in names) + ")"
            body = f"{code}\n\n{call}"
            glang = "python"
        gid = self.add_node(dify, "code", {"language": glang, "inputs": inputs, "code": body})
        self.attention(
            gid,
            _s(d.get("title")) or "코드",
            "코드가 제니오 방식(inputs로 받고 result에 넣기)에 맞게 감싸졌어요. 한 번 시험 실행해 확인해 주세요.",
        )
        self.done(gid, dify, "code", "code")

    @staticmethod
    def _kv_lines(raw: Any) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in _s(raw).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                if k.strip():
                    out[k.strip()] = v.strip()
        return out

    def _n_http_request(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        method = _s(d.get("method")).upper() or "GET"
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            self.warn(f"웹 요청 방식 '{method}'는 GET으로 바꿨어요.")
            method = "GET"
        url = self.text(d.get("url"))
        params = {k: self.text(v) for k, v in self._kv_lines(d.get("params")).items()}
        if params:
            q = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}{'&' if '?' in url else '?'}{q}"
        headers = {k: self.text(v) for k, v in self._kv_lines(d.get("headers")).items()}
        data: dict[str, Any] = {"method": method, "url": url}
        if headers:
            data["headers"] = headers
        body = _as_dict(d.get("body"))
        btype = _s(body.get("type"))
        bdata = body.get("data")
        if btype in ("json", "raw-text") and bdata is not None:
            if isinstance(bdata, list):
                bdata = " ".join(_s(_as_dict(x).get("value")) for x in bdata)
            text = self.text(bdata)
            if btype == "json":
                try:
                    data["body"] = json.loads(text)
                except ValueError:
                    data["body"] = text
            else:
                data["body"] = text
        elif btype in ("form-data", "x-www-form-urlencoded") and isinstance(bdata, list):
            data["body"] = {
                _s(_as_dict(x).get("key")): self.text(_as_dict(x).get("value"))
                for x in bdata
                if _as_dict(x).get("key")
            }
            self.warn(
                "웹 요청의 폼 형식 본문은 JSON 형식으로 바꿨어요. 받는 쪽이 폼만 받는지 확인해 주세요."
            )
        gid = self.add_node(dify, "http", data)
        auth = _as_dict(d.get("authorization"))
        if _s(auth.get("type")) not in ("", "no-auth"):
            cfg = _as_dict(auth.get("config"))
            kind = {
                "bearer": "Bearer 토큰",
                "basic": "아이디·비밀번호",
                "custom": f"헤더 '{_s(cfg.get('header'))}'",
            }.get(_s(cfg.get("type")), "API 키")
            self.attention(
                gid,
                _s(d.get("title")) or "웹 요청",
                f"인증({kind})의 키는 옮기지 않아요. 연결 정보에서 'HTTP 인증 정보'를 만들고 이 단계의 인증에서 골라 주세요.",
            )
        self.done(gid, dify, "http-request", "http")

    def _n_template_transform(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        tpl = _s(d.get("template"))
        names: dict[str, str] = {}
        for v in _as_list(d.get("variables")):
            v = _as_dict(v)
            r = self.ref(v.get("value_selector"))
            if v.get("variable") and r:
                names[_s(v["variable"])] = r[2:-2]  # {{ … }} 안쪽 경로

        def sub(m: re.Match[str]) -> str:
            inner = m.group(2)
            for name, path in names.items():
                inner = re.sub(rf"(?<![\w.]){re.escape(name)}\b", path, inner)
            return m.group(1) + inner + m.group(3)

        tpl = re.sub(r"(\{\{|\{%)(.*?)(\}\}|%\})", sub, tpl, flags=re.S)
        gid = self.add_node(dify, "template", {"template": tpl})
        self.done(gid, dify, "template-transform", "template")

    def _n_question_classifier(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        classes = []
        handles: dict[str, str] = {}
        for i, c in enumerate(_as_list(d.get("classes"))):
            c = _as_dict(c)
            cid = _s(c.get("id")) or str(i + 1)
            classes.append({"id": cid, "name": _s(c.get("name")) or cid, "description": ""})
            handles[cid] = cid
        q = self.ref(d.get("query_variable_selector")) or ("{{n1.message}}" if self.chat else "")
        data: dict[str, Any] = {"query": q, "classes": classes}
        instr = self.text(d.get("instruction"))
        if instr:
            data["instruction"] = instr
        note = self.model_note(d)
        if note:
            data["note"] = note
        gid = self.add_node(dify, "question_classifier", data)
        self.branch_maps[gid] = handles
        self.done(gid, dify, "question-classifier", "question_classifier")

    def _n_parameter_extractor(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        params = []
        for p in _as_list(d.get("parameters")):
            p = _as_dict(p)
            t = _s(p.get("type"))
            gt = (
                "number"
                if t == "number"
                else "boolean"
                if t == "bool"
                else "array"
                if t.startswith("array")
                else "string"
            )
            params.append(
                {
                    "name": _key(_s(p.get("name"))),
                    "type": gt,
                    "description": _s(p.get("description")),
                    "required": bool(p.get("required")),
                }
            )
        q = self.ref(d.get("query")) or ("{{n1.message}}" if self.chat else "")
        data: dict[str, Any] = {"query": q, "parameters": params}
        instr = self.text(d.get("instruction"))
        if instr:
            data["instruction"] = instr
        gid = self.add_node(dify, "parameter_extractor", data)
        self.done(gid, dify, "parameter-extractor", "parameter_extractor")

    def _n_variable_aggregator(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        refs = [self.ref(v) for v in _as_list(d.get("variables"))]
        gid = self.add_node(dify, "variable_aggregator", {"variables": [r for r in refs if r]})
        if _as_dict(d.get("advanced_settings")).get("group_enabled"):
            self.attention(
                gid,
                _s(d.get("title")) or "값 모으기",
                "그룹 기능은 옮기지 못했어요. 첫 번째 값만 이어 줘요.",
            )
        self.done(gid, dify, "variable-aggregator", "variable_aggregator")

    def _n_variable_assigner(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        # 옛 이름 'variable-assigner'는 값 모으기(variable-aggregator)와 같은 단계다
        if "variables" in d and "items" not in d and "assigned_variable_selector" not in d:
            self.types[_s(dify.get("id"))] = "variable-aggregator"
            self._n_variable_aggregator(dify, d)
            return
        self._n_assigner(dify, d)

    def _n_assigner(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        items = [_as_dict(i) for i in _as_list(d.get("items"))]
        if not items and d.get("assigned_variable_selector"):
            items = [
                {
                    "variable_selector": d.get("assigned_variable_selector"),
                    "operation": d.get("write_mode"),
                    "value": d.get("input_variable_selector"),
                    "input_type": "variable",
                }
            ]
        out: list[dict[str, str]] = []
        for it in items:
            sel = _as_list(it.get("variable_selector"))
            name = _key(_s(sel[1])) if len(sel) > 1 else ""
            op = _s(it.get("operation"))
            mode = {
                "over-write": "overwrite",
                "set": "overwrite",
                "append": "append",
                "extend": "append",
                "clear": "clear",
                "remove-first": "",
                "remove-last": "",
            }.get(op, "")
            if not name or not mode:
                self.warn(f"대화 값 '{name or '?'}'의 '{op}' 동작은 옮기지 못했어요.")
                continue
            val = it.get("value")
            value = self.ref(val) if isinstance(val, list) else self.text(val)
            out.append({"variable": name, "value": value, "mode": mode})
        gid = self.add_node(dify, "variable_assigner", {"assignments": out})
        self.done(gid, dify, "assigner", "variable_assigner")

    def _n_document_extractor(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        gid = self.add_node(
            dify,
            "document_extractor",
            {"file": self.ref(d.get("variable_selector")) or "{{n1.files}}"},
        )
        self.done(gid, dify, "document-extractor", "document_extractor")

    def _n_list_operator(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        data: dict[str, Any] = {"input": self.ref(d.get("variable"))}
        filt = _as_dict(d.get("filter_by"))
        conds = [_as_dict(c) for c in _as_list(filt.get("conditions"))]
        if filt.get("enabled") and conds:
            c = conds[0]
            op = {
                "contains": "contains",
                "not contains": "not_contains",
                "is": "eq",
                "=": "eq",
                "is not": "ne",
                "≠": "ne",
                ">": "gt",
                "<": "lt",
                "empty": "is_empty",
                "not empty": "not_empty",
            }.get(_s(c.get("comparison_operator")), "")
            if op:
                data["filter"] = {
                    "key": _s(c.get("key")),
                    "operator": op,
                    "value": self.text(c.get("value")),
                }
            else:
                self.warn(f"목록 거르기 연산자 '{c.get('comparison_operator')}'는 옮기지 못했어요.")
            if len(conds) > 1:
                self.warn("목록 거르기 조건이 여러 개라 첫 번째만 옮겼어요.")
        order = _as_dict(d.get("order_by"))
        if order.get("enabled"):
            data["sort"] = {
                "enabled": True,
                "key": _s(order.get("key")),
                "order": "desc" if _s(order.get("value")) == "desc" else "asc",
            }
        lim = _as_dict(d.get("limit"))
        if lim.get("enabled") and isinstance(lim.get("size"), int):
            data["limit"] = lim["size"]
        gid = self.add_node(dify, "list_operator", data)
        self.done(gid, dify, "list-operator", "list_operator")

    # ---- 반복·되풀이(하위 단계가 하나일 때만) ----
    def _children(self, did: str) -> list[dict[str, Any]]:
        out = []
        for n in _as_list(_as_dict(_as_dict(self.doc.get("workflow")).get("graph")).get("nodes")):
            n = _as_dict(n)
            nd = _as_dict(n.get("data"))
            if (
                n.get("parentId") == did
                or nd.get("iteration_id") == did
                or nd.get("loop_id") == did
            ) and _s(nd.get("type")) not in ("iteration-start", "loop-start", "loop-end"):
                out.append(n)
        return out

    def _child_operation(
        self, did: str, kind: str, dify: dict[str, Any]
    ) -> tuple[dict[str, Any], str, str] | None:
        kids = self._children(did)
        if len(kids) != 1:
            return None
        kid = kids[0]
        kd = _as_dict(kid.get("data"))
        ktype = _s(kd.get("type"))
        self.iter_scope[did] = kind
        self.in_scope = did
        try:
            if ktype == "llm":
                llm = {k: v for k, v in self._llm_data(kd).items() if k != "note"}
                return {"type": "llm", "data": llm}, ktype, _s(kid.get("id"))
            if ktype == "template-transform":
                tmp = _Converter(self.doc)
                tmp.ids, tmp.types, tmp.start_id, tmp.start_vars = (
                    self.ids,
                    self.types,
                    self.start_id,
                    self.start_vars,
                )
                tmp.iter_scope, tmp.in_scope, tmp.chat = self.iter_scope, self.in_scope, self.chat
                tmp.nodes = [{"type": "input", "data": {"fields": []}}]
                tmp._n_template_transform(kid, kd)
                return (
                    {"type": "template", "data": {"template": tmp.nodes[-1]["data"]["template"]}},
                    ktype,
                    _s(kid.get("id")),
                )
            if ktype == "http-request":
                tmp = _Converter(self.doc)
                tmp.ids, tmp.types, tmp.start_id, tmp.start_vars = (
                    self.ids,
                    self.types,
                    self.start_id,
                    self.start_vars,
                )
                tmp.iter_scope, tmp.in_scope, tmp.chat = self.iter_scope, self.in_scope, self.chat
                tmp.nodes = [{"type": "input", "data": {"fields": []}}]
                tmp._n_http_request(kid, kd)
                self.report.warnings.extend(
                    w for w in tmp.report.warnings if w not in self.report.warnings
                )
                self.report.needs_attention.extend(tmp.report.needs_attention)
                data = {
                    k: v for k, v in tmp.nodes[-1]["data"].items() if k not in ("label", "note")
                }
                return {"type": "http", "data": data}, ktype, _s(kid.get("id"))
        finally:
            self.in_scope = ""
        return None
        return None

    def _n_iteration(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        did = _s(dify.get("id"))
        res = self._child_operation(did, "iteration", dify)
        if res is None:
            self.placeholder(
                dify,
                "iteration",
                "반복 안에 단계가 여러 개이거나 지원하지 않는 단계라 옮기지 못했어요.",
            )
            return
        op, ktype, _kid = res
        out_sel = [_s(x) for x in _as_list(d.get("output_selector"))]
        out_key = FIELD_MAP.get(ktype, {}).get(out_sel[1], out_sel[1]) if len(out_sel) > 1 else ""
        self.in_scope = ""
        items = self.ref(d.get("iterator_selector"))
        data = {"items": items, "operation": op, "output_key": out_key, "max_items": 100}
        gid = self.add_node(dify, "iteration", data)
        self.done(gid, dify, "iteration", "iteration")

    def _n_loop(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        did = _s(dify.get("id"))
        res = self._child_operation(did, "loop", dify)
        if res is None:
            self.placeholder(
                dify,
                "loop",
                "되풀이 안에 단계가 여러 개이거나 지원하지 않는 단계라 옮기지 못했어요.",
            )
            return
        op, ktype, _kid = res
        count = d.get("loop_count")
        lv = [_as_dict(v) for v in _as_list(d.get("loop_variables"))]
        initial = _s(lv[0].get("value")) if lv else ""
        data: dict[str, Any] = {
            "operation": op,
            "output_key": "text" if ktype == "llm" else "output",
            "max_iterations": max(1, min(int(count), 20)) if isinstance(count, int) else 3,
        }
        if initial:
            data["initial"] = initial
        gid = self.add_node(dify, "loop", data)
        if d.get("break_conditions"):
            self.attention(
                gid,
                _s(d.get("title")) or "되풀이",
                "멈춤 조건은 옮기지 못했어요. 필요하면 '멈춤 조건'을 직접 적어 주세요.",
            )
        self.done(gid, dify, "loop", "loop")

    def _n_agent(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        params = _as_dict(d.get("agent_parameters"))
        data: dict[str, Any] = {
            "provider": "default",
            "instruction": self.value_of(params.get("instruction")),
            "query": self.value_of(params.get("query")) or ("{{n1.message}}" if self.chat else ""),
        }
        mi = _as_dict(params.get("maximum_iterations")).get("value", d.get("max_iterations"))
        if isinstance(mi, int):
            data["max_iterations"] = max(1, min(mi, 10))
        gid = self.add_node(dify, "agent", data)
        tools = _as_list(_as_dict(params.get("tools")).get("value"))
        if tools:
            names = ", ".join(_s(_as_dict(t).get("tool_name")) for t in tools)
            self.attention(
                gid,
                _s(d.get("title")) or "에이전트",
                f"Dify 도구({names})는 옮기지 못했어요. 이 단계의 '쓸 수 있는 도구'를 다시 정해 주세요.",
            )
        self.done(gid, dify, "agent", "agent")

    def _n_human_input(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        msg = self.text(d.get("form_content")) or _s(d.get("title")) or "확인해 주세요"
        inputs = _as_list(d.get("inputs"))
        actions = [_as_dict(a) for a in _as_list(d.get("user_actions"))]
        if inputs:
            fields = [
                {
                    "key": _key(_s(_as_dict(i).get("output_variable_name"))),
                    "label": _s(_as_dict(i).get("output_variable_name")),
                    "type": "text",
                    "required": True,
                }
                for i in inputs
            ]
            gid = self.add_node(dify, "ask_person", {"question": msg[:300], "fields": fields})
            self.done(gid, dify, "human-input", "ask_person")
            if actions:
                self.attention(
                    gid,
                    _s(d.get("title")) or "사람 확인",
                    "버튼(승인·반려 등)에 따른 갈래는 옮기지 못했어요. 다음 단계로 한 줄로 이어져요.",
                )
            return
        gid = self.add_node(dify, "approval", {"message": msg, "branch": True})
        handles: dict[str, str] = {}
        if actions:
            handles[_s(actions[0].get("id"))] = "approved"
        if len(actions) > 1:
            handles[_s(actions[1].get("id"))] = "rejected"
        if len(actions) > 2:
            self.attention(
                gid,
                _s(d.get("title")) or "사람 확인",
                "버튼이 3개 이상이라 앞의 두 개만 승인·반려로 옮겼어요.",
            )
        self.branch_maps[gid] = handles
        self.done(gid, dify, "human-input", "approval")

    def _n_tool(self, dify: dict[str, Any], d: dict[str, Any]) -> None:
        name = _s(d.get("tool_name") or d.get("tool_label"))
        prov = _s(d.get("provider_name") or d.get("provider_id"))
        self.placeholder(
            dify,
            "tool",
            f"Dify 도구 '{prov} {name}'는 마켓 연결이나 웹 요청 단계로 다시 만들어 주세요.",
        )


# ---------------- 앱 기능 ----------------
def _features(src: dict[str, Any]) -> dict[str, Any]:
    f: dict[str, Any] = {}
    if _s(src.get("opening_statement")):
        f["opening_statement"] = _s(src["opening_statement"])[:500]
    sq = [str(q) for q in _as_list(src.get("suggested_questions")) if str(q).strip()]
    if sq:
        f["suggested_questions"] = sq[:6]
    if _as_dict(src.get("suggested_questions_after_answer")).get("enabled"):
        f["follow_up"] = {"enabled": True}
    if _as_dict(src.get("retriever_resource")).get("enabled"):
        f["citations"] = {"enabled": True}
    stt = bool(_as_dict(src.get("speech_to_text")).get("enabled"))
    tts = bool(_as_dict(src.get("text_to_speech")).get("enabled"))
    if stt or tts:
        f["speech"] = {"stt": stt, "tts": tts}
    fu = _as_dict(src.get("file_upload"))
    if fu.get("enabled") or _as_dict(fu.get("image")).get("enabled"):
        n = _as_dict(fu.get("image")).get("number_limits") or fu.get("number_limits") or 3
        f["file_upload"] = {"enabled": True, "max_files": int(n) if isinstance(n, int) else 3}
    sw = _as_dict(src.get("sensitive_word_avoidance"))
    if sw.get("enabled"):
        cfg = _as_dict(sw.get("config"))
        words = [w.strip() for w in re.split(r"[\n,]", _s(cfg.get("keywords"))) if w.strip()]
        if words:
            f["moderation"] = {
                "enabled": True,
                "keywords": words,
                "preset_reply": _s(_as_dict(cfg.get("inputs_config")).get("preset_response"))
                or "그 내용에는 답할 수 없어요.",
                "check_output": bool(_as_dict(cfg.get("outputs_config")).get("enabled")),
            }
    return f


def _env_vars(items: Any, rep: Report) -> list[dict[str, Any]]:
    out = []
    for v in _as_list(items):
        v = _as_dict(v)
        name = _key(_s(v.get("name")), "")
        if not name:
            continue
        secret = _s(v.get("value_type")) == "secret"
        out.append({"key": name, "secret": secret, "value": "" if secret else _s(v.get("value"))})
        if secret:
            rep.needs_attention.append(
                {
                    "node": "",
                    "label": f"환경 값 {name}",
                    "message": "비밀 값은 옮기지 않아요. 앱 기능 > 환경 값에서 다시 넣어 주세요.",
                }
            )
    return out


# ---------------- 앱 모드별 ----------------
def _basic_form(items: Any) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for it in _as_list(items):
        for kind, cfg in _as_dict(it).items():
            cfg = _as_dict(cfg)
            var = _s(cfg.get("variable"))
            if not var:
                continue
            ftype = {"number": "number"}.get(kind, "text")
            if kind in ("file", "file-list"):
                ftype = "file"
            label = _s(cfg.get("label")) or var
            if kind == "select":
                opts = ", ".join(_s(o) for o in _as_list(cfg.get("options")))
                label = f"{label} (선택: {opts})" if opts else label
            fields.append(
                {
                    "key": _key(var),
                    "label": label[:60],
                    "type": ftype,
                    "required": bool(cfg.get("required")),
                }
            )
    return fields


def _convert_model_config(
    doc: dict[str, Any], mode: str, rep: Report
) -> tuple[dict[str, Any], dict[str, Any], str]:
    mc = _as_dict(doc.get("model_config"))
    chat = mode in ("chat", "agent-chat")
    fields = _basic_form(mc.get("user_input_form"))
    if chat:
        rest = [{**f, "key": "message_1"} if f["key"] == "message" else f for f in fields]
        fields = [{"key": "message", "label": "질문", "type": "text", "required": True}, *rest]
    elif not fields:
        fields = [{"key": "text", "label": "내용", "type": "text", "required": True}]
    names = {f["key"] for f in fields}
    pre = _s(mc.get("pre_prompt"))
    pre = re.sub(
        r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}",
        lambda m: "{{n1." + m.group(1) + "}}" if m.group(1) in names else m.group(0),
        pre,
    )
    model = _as_dict(mc.get("model"))
    note = f"원래 모델: {_s(model.get('provider')).split('/')[-1]} {_s(model.get('name'))}".strip()
    nodes: list[dict[str, Any]] = [
        {
            "id": "n1",
            "type": "input",
            "position": {"x": 0, "y": 0},
            "data": {"label": "시작", "fields": fields},
        }
    ]
    edges: list[tuple[str, str]] = []
    dsets = _as_dict(_as_dict(mc.get("dataset_configs")).get("datasets")).get("datasets")
    datasets = [
        x for x in _as_list(dsets) if _as_dict(_as_dict(x).get("dataset")).get("enabled", True)
    ]
    if mode == "agent-chat":  # 에이전트 앱은 도구 목록 안에 지식베이스가 들어 있다
        datasets += [
            t
            for t in _as_list(_as_dict(mc.get("agent_mode")).get("tools"))
            if "dataset" in _as_dict(t)
        ]
    x = 320
    last = "n1"
    kb_ref = ""
    if datasets:
        nodes.append(
            {
                "id": "n2",
                "type": "knowledge_search",
                "position": {"x": x, "y": 0},
                "data": {
                    "label": "지식 검색",
                    "kb_id": "",
                    "query": "{{n1.message}}" if chat else "{{n1." + fields[0]["key"] + "}}",
                },
            }
        )
        edges.append((last, "n2"))
        last = "n2"
        x += 320
        kb_ref = "{{n2.context}}"
        rep.needs_attention.append(
            {
                "node": "n2",
                "label": "지식 검색",
                "message": f"Dify 지식베이스 {len(datasets)}개는 옮겨지지 않아요. 같은 문서를 올리고 이 단계에서 골라 주세요.",
            }
        )
    gid = f"n{len(nodes) + 1}"
    if mode == "agent-chat":
        am = _as_dict(mc.get("agent_mode"))
        tools = [
            _as_dict(t)
            for t in _as_list(am.get("tools"))
            if "dataset" not in _as_dict(t) and _as_dict(t).get("enabled", True)
        ]
        data = {
            "label": "에이전트",
            "provider": "default",
            "instruction": pre,
            "query": "{{n1.message}}",
            "note": note,
            "max_iterations": max(1, min(int(am.get("max_iteration") or 5), 10))
            if isinstance(am.get("max_iteration"), int)
            else 5,
        }
        if kb_ref:
            data["instruction"] = (pre + "\n\n참고 자료:\n" + kb_ref).strip()
        nodes.append({"id": gid, "type": "agent", "position": {"x": x, "y": 0}, "data": data})
        if tools:
            rep.needs_attention.append(
                {
                    "node": gid,
                    "label": "에이전트",
                    "message": "Dify 도구("
                    + ", ".join(_s(t.get("tool_name")) for t in tools)
                    + ")는 옮기지 못했어요. '쓸 수 있는 도구'를 다시 정해 주세요.",
                }
            )
        out_ref = "{{" + gid + ".text}}"
        rep.converted.append(
            {"node": gid, "label": "에이전트", "dify_type": "agent-chat", "genio_type": "agent"}
        )
    else:
        system = pre + (("\n\n참고 자료:\n" + kb_ref) if kb_ref else "")
        prompt = "{{n1.message}}" if chat else (pre or "내용을 정리해 주세요.")
        data = {"label": "AI 답변", "provider": "default", "prompt": prompt, "note": note}
        if chat:
            if system.strip():
                data["system"] = system.strip()
            data["memory"] = True
        elif kb_ref:
            data["prompt"] = prompt + "\n\n참고 자료:\n" + kb_ref
        temp = _as_dict(model.get("completion_params")).get("temperature")
        if isinstance(temp, int | float) and 0 <= temp <= 2:
            data["temperature"] = float(temp)
        nodes.append({"id": gid, "type": "llm", "position": {"x": x, "y": 0}, "data": data})
        out_ref = "{{" + gid + ".text}}"
        rep.converted.append(
            {"node": gid, "label": "AI 답변", "dify_type": mode, "genio_type": "llm"}
        )
    edges.append((last, gid))
    rep.needs_attention.append(
        {
            "node": gid,
            "label": "AI 답변",
            "message": f"{note}. 관리 > AI 모델에서 쓸 모델을 정해 주세요.",
        }
    )
    oid = f"n{len(nodes) + 1}"
    nodes.append(
        {
            "id": oid,
            "type": "output",
            "position": {"x": x + 320, "y": 0},
            "data": {"label": "결과", "template": out_ref},
        }
    )
    edges.append((gid, oid))
    rep.converted.insert(
        0, {"node": "n1", "label": "시작", "dify_type": mode, "genio_type": "input"}
    )
    rep.converted.append({"node": oid, "label": "결과", "dify_type": mode, "genio_type": "output"})
    graph = {
        "version": 1,
        "nodes": nodes,
        "edges": [{"id": f"e{i + 1}", "source": s, "target": t} for i, (s, t) in enumerate(edges)],
        "variables": {},
    }
    features = _features(mc)
    if "{{" in _s(features.get("opening_statement")):
        rep.warnings.append(
            "시작 인사 글 안의 {{변수}}는 제니오에서 채워지지 않아요. 글을 직접 고쳐 주세요."
        )
    if mode == "completion":
        rep.warnings.append("문장 완성형(completion) 앱은 AI 단계 하나짜리 흐름으로 바꿨어요.")
    return graph, features, ("chat" if chat else "workflow")


# ---------------- 진입점 ----------------
def convert(raw: bytes | str) -> Converted:
    doc = parse_text(raw)
    app = _as_dict(doc.get("app"))
    wf = _as_dict(doc.get("workflow"))
    if not app and "graph" in doc:  # 안쪽 YAML만 붙여 넣은 경우
        wf = {
            "graph": doc["graph"],
            "features": doc.get("features"),
            "environment_variables": doc.get("environment_variables"),
        }
        app = {"mode": "workflow", "name": _s(doc.get("name"))}
    if not app and not wf and not doc.get("model_config"):
        raise _not_dify()
    mode = _s(app.get("mode")) or ("workflow" if wf else "chat")
    if mode not in SUPPORTED_MODES:
        raise AppError(
            422,
            f"'{mode}' 형식의 Dify 앱은 아직 가져올 수 없어요.",
            "워크플로우·챗플로우·챗봇·에이전트·문장 완성 앱만 가져올 수 있어요.",
        )
    name = _s(app.get("name")) or "Dify에서 가져온 앱"
    icon = _s(app.get("icon")) if _s(app.get("icon_type") or "emoji") == "emoji" else ""
    rep = Report(mode=mode, dify_version=_s(doc.get("version")))
    description = _s(app.get("description"))[:2000]

    if mode in ("workflow", "advanced-chat"):
        graph_src = _as_dict(wf.get("graph"))
        nodes_src = [_as_dict(n) for n in _as_list(graph_src.get("nodes"))]
        if len(nodes_src) > MAX_NODES:
            raise AppError(422, "단계가 너무 많아요(최대 300개).", "앱을 나눠서 가져와 주세요.")
        if not nodes_src:
            raise AppError(
                422, "흐름에 단계가 없어요.", "Dify에서 단계를 하나 이상 만든 뒤 내보내 주세요."
            )
        cv = _Converter(doc)
        cv.chat = mode == "advanced-chat"
        cv.report = rep
        skip: set[str] = set()
        top: list[dict[str, Any]] = []
        for n in nodes_src:
            nd = _as_dict(n.get("data"))
            ntype = _s(nd.get("type"))
            if _s(n.get("type")) == "custom-note" or (ntype == "" and "text" in nd):
                cv.notes.append(
                    {
                        "id": f"note{len(cv.notes) + 1}",
                        "text": _plain_text(_s(nd.get("text")))[:5000],
                        "position": {
                            "x": float(_as_dict(n.get("position")).get("x") or 0),
                            "y": float(_as_dict(n.get("position")).get("y") or 0),
                        },
                        "color": "yellow",
                    }
                )
                skip.add(_s(n.get("id")))
                continue
            if (
                n.get("parentId")
                or nd.get("isInIteration")
                or nd.get("isInLoop")
                or ntype in ("iteration-start", "loop-start", "loop-end")
            ):
                skip.add(_s(n.get("id")))
                continue
            top.append(n)
        # 시작 단계를 먼저 바꿔 두면 n1이 시작 단계가 된다
        top.sort(key=lambda n: 0 if _s(_as_dict(n.get("data")).get("type")) == "start" else 1)
        if not any(_s(_as_dict(n.get("data")).get("type")) == "start" for n in top):
            cv.chat = mode == "advanced-chat"
            fields = [
                {
                    "key": "message",
                    "label": "질문" if cv.chat else "입력",
                    "type": "text",
                    "required": True,
                }
            ]
            cv.nodes.append(
                {
                    "id": "n1",
                    "type": "input",
                    "position": {"x": 0, "y": 0},
                    "data": {"label": "시작", "fields": fields},
                }
            )
            rep.warnings.append(
                "시작 단계가 없어 입력 단계를 새로 만들었어요(연결은 직접 이어 주세요)."
            )
        for n in top:
            cv.convert_node(n)
        # 연결
        for e in _as_list(graph_src.get("edges")):
            e = _as_dict(e)
            s, t = _s(e.get("source")), _s(e.get("target"))
            if s in skip or t in skip:
                continue
            gs, gt = cv.ids.get(s), cv.ids.get(t)
            if not gs or not gt or gs == gt:
                continue
            h = _s(e.get("sourceHandle"))
            edge: dict[str, Any] = {"source": gs, "target": gt}
            bm = cv.branch_maps.get(gs)
            if bm is not None:
                mapped = bm.get(h)
                if not mapped:
                    cv.warn(f"갈래 '{h}'로 가는 연결 하나는 옮기지 못했어요.")
                    continue
                edge["sourceHandle"] = mapped
            if edge in [{k: v for k, v in x.items() if k != "id"} for x in cv.edges]:
                continue
            cv.edges.append({"id": f"e{len(cv.edges) + 1}", **edge})
        # 위치: 왼쪽 위가 0,0이 되게
        if cv.nodes:
            mx = min(n["position"]["x"] for n in cv.nodes)
            my = min(n["position"]["y"] for n in cv.nodes)
            for n in cv.nodes:
                n["position"] = {
                    "x": round(n["position"]["x"] - mx),
                    "y": round(n["position"]["y"] - my),
                }
            for note in cv.notes:
                note["position"] = {
                    "x": round(note["position"]["x"] - mx),
                    "y": round(note["position"]["y"] - my),
                }
        graph: dict[str, Any] = {
            "version": 1,
            "nodes": cv.nodes,
            "edges": cv.edges,
            "variables": {},
        }
        if cv.notes:
            graph["notes"] = cv.notes
        feats = _features(_as_dict(wf.get("features")))
        env = _env_vars(wf.get("environment_variables"), rep)
        if _as_list(wf.get("conversation_variables")):
            names = ", ".join(
                _s(_as_dict(v).get("name")) for v in _as_list(wf.get("conversation_variables"))
            )
            rep.warnings.append(
                f"대화 변수({names})의 처음 값은 옮기지 않아요. 첫 대화에서는 비어 있으니 '값 저장' 단계로 채워 주세요."
            )
        app_type = "chat" if mode == "advanced-chat" else "workflow"
    else:
        graph, feats, app_type = _convert_model_config(doc, mode, rep)
        env = []
    return Converted(
        name=name[:100],
        description=description,
        icon=icon[:40],
        app_type=app_type,
        graph=graph,
        features=feats,
        env_vars=env,
        report=rep,
    )
