"""실패한 실행의 자동 진단: 실패 단계의 오류 글과 단계 종류로 '이렇게 고칠까요?' 제안을 만든다.

AI를 부르지 않는다(실패 순간 바로 보여 주고 비용이 없게). 제안 하나는 버튼이고, 누르면 그 문장이
빌더에게 가서 고치기 시작한다. 마지막 제안(원인 찾기)은 늘 붙는다.
"""

import re
from typing import Any

# (이름, 오류 글 패턴, 단계 종류(없으면 전부), 버튼 글, 빌더에게 보낼 말)
_RULES: list[tuple[str, str, set[str] | None, str, str]] = [
    (
        "auth",
        r"연결 정보|인증|401|403|권한|토큰이 (?:없|잘못|만료)|키가 (?:없|잘못)|api key|unauthorized|forbidden",
        None,
        "연결 정보 다시 고르기",
        "{label} 단계가 인증 문제로 실패했어요. 맞는 연결 정보를 다시 고르게 해 주고, 없으면 만들어야 할 것을 알려 줘.",
    ),
    (
        "timeout",
        r"시간 초과|오래 걸|timeout|timed out",
        None,
        "제한 시간 늘리고 다시 시도하게",
        "{label} 단계가 시간 초과로 실패했어요. 제한 시간을 넉넉히 늘리고 재시도를 2번으로 해 줘.",
    ),
    (
        "missing_value",
        r"비어|없는 값|찾을 수 없|참조|undefined|none|\{\{|필수 값|값이 없",
        None,
        "앞 단계 값 연결 고치기",
        "{label} 단계에서 값이 비어 실패했어요. 앞 단계에서 끌어오는 값 연결을 확인해서 고쳐 줘.",
    ),
    (
        "format",
        r"json|형식|스키마|파싱|읽지 못|schema|parse",
        None,
        "출력 형식 맞추기",
        "{label} 단계의 값 형식이 맞지 않아 실패했어요. 받는 쪽과 보내는 쪽의 형식을 맞춰 줘.",
    ),
    (
        "model",
        r"한도|rate|quota|모델|토큰이 너무|context|길이",
        {"llm", "agent", "classifier", "extractor", "image"},
        "AI 설정 점검하기",
        "{label} 단계가 AI 호출에서 실패했어요. 모델·글 길이·한도를 점검해서 고쳐 줘.",
    ),
    (
        "network",
        r"연결하지 못|접속|dns|connection|network|주소|호스트",
        {"http", "connector", "db", "mcp", "api_tool"},
        "주소·연결 확인하기",
        "{label} 단계가 외부에 연결하지 못해 실패했어요. 주소와 연결 설정을 확인해서 고쳐 줘.",
    ),
]
_FALLBACK = (
    "generic",
    "원인을 찾아 고치기",
    "{label} 단계가 실패했어요. 원인을 찾아서 고치고, 고친 뒤 시험해 줘.",
)
_SAFETY = (
    "continue",
    "실패해도 계속 진행하게",
    "{label} 단계가 실패해도 흐름이 멈추지 않도록 실패하면 기본값으로 계속하게 설정해 줘.",
)


def diagnose(
    run: dict[str, Any], steps: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """실패한 실행이 아니면 None. 아니면 실패 단계와 제안 목록."""
    if run.get("status") != "failed":
        return None
    failed = next((s for s in steps if s.get("status") == "failed"), None)
    node = nodes.get(str((failed or {}).get("node_id") or ""))
    ntype = str((node or {}).get("type") or "")
    label = str(((node or {}).get("data") or {}).get("label") or "실패한")
    text = " ".join([str((failed or {}).get("logs") or ""), str(run.get("error") or "")]).lower()
    suggestions: list[dict[str, str]] = []
    for key, pattern, types, button, prompt in _RULES:
        if types is not None and ntype not in types:
            continue
        if re.search(pattern, text, re.IGNORECASE):
            suggestions.append({"id": key, "label": button, "prompt": prompt.format(label=label)})
        if len(suggestions) == 2:
            break
    if ntype in {"http", "connector", "llm", "db", "mcp", "api_tool"}:
        suggestions.append(
            {"id": _SAFETY[0], "label": _SAFETY[1], "prompt": _SAFETY[2].format(label=label)}
        )
    suggestions.append(
        {"id": _FALLBACK[0], "label": _FALLBACK[1], "prompt": _FALLBACK[2].format(label=label)}
    )
    return {
        "node_id": (failed or {}).get("node_id"),
        "node_label": label,
        "node_type": ntype,
        "suggestions": suggestions,
    }
