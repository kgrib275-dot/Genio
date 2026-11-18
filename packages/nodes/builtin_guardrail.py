"""가드레일 단계: 글을 검사해서 개인정보·탈옥(지시 무시) 시도·금칙어·너무 긴 글을 걸러 낸다.

AI를 부르지 않는 규칙 검사라 비용이 없고 늘 같은 결과가 나온다(전부 잡아내지는 못한다. 중요한 곳에서는
AI 단계의 지시문 방어와 함께 쓴다). 결과는 `passed`(통과 여부)로 내므로 다음에 '조건 분기'를 두면 갈래를
나눌 수 있고, '걸리면 멈추기'를 고르면 그 자리에서 멈춘다.
"""

import re
from typing import Any

from nodes.spec import NodeContext, NodeError, NodeRegistry, NodeResult, NodeSpec

MAX_BANNED = 200
MAX_TEXT = 200_000

# 탈옥·프롬프트 주입 흔한 문구(한국어·영어). 완전하지 않다.
_JAILBREAK = [
    r"(이전|위|앞)(의|에)?\s*(모든\s*)?(지시|명령|규칙|프롬프트)(를|은|는)?\s*(모두\s*)?(무시|잊어|따르지)",
    r"(시스템|system)\s*(프롬프트|prompt|지시)(를|을)?\s*(알려|보여|출력|말해|공개)",
    r"(너는|넌|당신은)\s*이제\s*(부터)?\s*.{0,20}(다|야)\s*(역할|모드)",
    r"(제한|규칙|안전\s*장치|필터)(을|를)?\s*(없|해제|끄|우회|무시)",
    r"개발자\s*모드|탈옥|제약\s*없는\s*(ai|모드)",
    r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above)\s+(instructions|rules|prompts?)",
    r"(reveal|show|print|repeat)\s+(your\s+|the\s+)?(system\s+)?(prompt|instructions)",
    r"disregard\s+(your|the|all)\s+(rules|guidelines|instructions)",
    r"\b(dan|developer)\s+mode\b|jailbreak|do\s+anything\s+now",
    r"you\s+are\s+now\s+(?:an?\s+)?(?:unrestricted|unfiltered|evil)",
]
_JAILBREAK_RE = [re.compile(p, re.IGNORECASE) for p in _JAILBREAK]


def jailbreak_hits(text: str) -> list[str]:
    """걸린 문구(앞 40자)를 돌려준다."""
    hits: list[str] = []
    for rx in _JAILBREAK_RE:
        m = rx.search(text)
        if m:
            hits.append(m.group(0)[:40])
    return hits


def _words(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = re.split(r"[,\n]", raw)
    out: list[str] = []
    for w in raw or []:
        t = str(w).strip()
        if t and t.lower() not in (x.lower() for x in out):
            out.append(t[:60])
    return out[:MAX_BANNED]


def _run(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    text = ctx.render(str(data.get("text") or ""))[:MAX_TEXT]
    pii_mode = str(data.get("pii") or "off")
    if pii_mode not in ("off", "mask", "block"):
        pii_mode = "off"
    reasons: list[str] = []
    notes: list[str] = []
    out_text = text

    if pii_mode != "off":
        mask_fn = getattr(ctx.services, "mask_text", None)
        if mask_fn is None:
            raise NodeError(
                "이 환경에서는 개인정보 검사를 쓸 수 없어요. 개인정보 검사를 '안 함'으로 바꾸세요."
            )
        masked = str(mask_fn(text))
        if masked != text:
            if pii_mode == "block":
                reasons.append("개인정보가 들어 있어요")
            else:
                notes.append("개인정보를 가렸어요")
                out_text = masked

    if data.get("jailbreak", True):
        hits = jailbreak_hits(text)
        if hits:
            reasons.append("지시를 무시하게 만들려는 문구가 있어요")
            ctx.log(f"탈옥 의심 문구: {hits[0]}")

    lowered = text.lower()
    found = [w for w in _words(data.get("banned_words")) if w.lower() in lowered]
    if found:
        reasons.append(f"금지어가 있어요({', '.join(found[:3])})")

    try:
        max_len = int(data.get("max_length") or 0)
    except (TypeError, ValueError):
        max_len = 0
    if max_len > 0 and len(text) > max_len:
        reasons.append(f"글이 너무 길어요({len(text)}자, 최대 {max_len}자)")

    passed = not reasons
    ctx.log(f"가드레일 결과: {'통과' if passed else '걸림'} {reasons or notes}")
    if not passed and str(data.get("on_fail") or "continue") == "stop":
        raise NodeError(f"안전 검사에 걸렸어요: {reasons[0]}. 내용을 바꿔서 다시 시도하세요.")
    return NodeResult(
        output={
            "passed": passed,
            "blocked": not passed,
            "reasons": reasons,
            "notes": notes,
            "text": out_text,
        }
    )


GUARDRAIL = NodeSpec(
    type="guardrail",
    label="안전 검사",
    category="AI",
    description=(
        "글에 개인정보·'이전 지시를 무시해' 같은 탈옥 문구·금지어가 있는지, 너무 긴지 검사해요. "
        "결과의 '통과 여부'가 참이면 통과예요. 다음에 '조건 분기' 단계를 두어 걸린 글을 따로 처리하거나, "
        "'걸리면 멈추기'로 그 자리에서 멈출 수 있어요. 규칙 검사라 비용이 없고 모든 경우를 잡지는 못해요."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "label": {"type": "string", "title": "이름"},
            "text": {"type": "string", "title": "검사할 글(예: {{n1.message}})"},
            "pii": {
                "type": "string",
                "title": "개인정보",
                "enum": ["off", "mask", "block"],
                "enumNames": ["검사 안 함", "찾으면 가려서 넘기기", "찾으면 걸림으로 처리"],
                "default": "off",
            },
            "jailbreak": {
                "type": "boolean",
                "title": "속이는 문구 검사(예: 이전 지시를 무시해)",
                "default": True,
            },
            "banned_words": {
                "type": "array",
                "title": "금지어",
                "items": {"type": "string"},
            },
            "max_length": {
                "type": "number",
                "title": "최대 글자 수(0이면 제한 없음)",
                "minimum": 0,
                "default": 0,
            },
            "on_fail": {
                "type": "string",
                "title": "걸리면",
                "enum": ["continue", "stop"],
                "enumNames": ["계속 진행(passed로 갈래 나누기)", "그 자리에서 멈추기"],
                "default": "continue",
            },
        },
        "required": ["text"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "blocked": {"type": "boolean"},
            "reasons": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "array", "items": {"type": "string"}},
            "text": {"type": "string"},
        },
    },
    ui_schema={},
    run=_run,
    outputs=lambda d: ["passed", "blocked", "reasons", "notes", "text"],
)


def register_guardrail(reg: NodeRegistry) -> None:
    if reg.get(GUARDRAIL.type) is None:
        reg.register(GUARDRAIL)
