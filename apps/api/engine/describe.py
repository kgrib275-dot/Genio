"""실행 결과를 문장으로 설명한다(기능 정의서 S3).

예: "분류 단계에서 '결제 문의'로 판단했어요 (0.8초)". JSON은 화면에서 펼쳐 보기로만 보인다.
run_detail(routers/runs.py)이 이 함수들을 불러 각 단계에 summary, 실행 전체에 story를 붙인다.

규칙
- 비밀값은 절대 문장에 넣지 않는다. 연결(커넥터) 단계는 서비스·동작·채널·받는 사람처럼
  눈에 보이는 대상만 쓰고, 토큰·키·비밀번호 같은 값은 보지 않는다.
- 값은 짧게 자른다(문장 하나가 화면 한 줄을 넘지 않게).
- 실패한 단계는 "무엇이 문제 + 어떻게 하면 되는지" 두 줄.
"""

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

MAX_VALUE = 40
# 연결 단계에서 대상으로 보여 줘도 되는 값(채널·받는 사람·시트 이름 등)
_TARGET_KEYS = ("channel", "to", "recipient", "sheet", "spreadsheet_id", "range", "subject")
_SECRET_HINT = re.compile(r"(token|secret|password|passwd|api[_-]?key|authorization)", re.I)

_GENERIC_FIX = (
    "설정을 확인한 뒤 다시 실행해 보세요. 어려우면 '빌더에게 고쳐 달라고 하기'를 누르세요."
)


def _short(value: Any, limit: int = MAX_VALUE) -> str:
    text = value if isinstance(value, str) else str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _duration(step: dict[str, Any]) -> str:
    start, end = step.get("started_at"), step.get("finished_at")
    if isinstance(start, str):
        start = _parse(start)
    if isinstance(end, str):
        end = _parse(end)
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        return ""
    sec = max(0.0, (end - start).total_seconds())
    return f" ({sec:.1f}초)" if sec < 60 else f" ({int(sec // 60)}분 {int(sec % 60)}초)"


def _parse(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _out(step: dict[str, Any]) -> dict[str, Any]:
    out = step.get("output")
    return out if isinstance(out, dict) else {}


def _data(node: dict[str, Any] | None, step: dict[str, Any]) -> dict[str, Any]:
    data = (node or {}).get("data")
    if isinstance(data, dict):
        return data
    inp = step.get("input")
    return inp if isinstance(inp, dict) else {}


def failure_lines(step: dict[str, Any]) -> tuple[str, str]:
    """실패한 단계의 (문제, 고치는 방법). 오류 문구가 두 문장이면 나눠 쓴다."""
    logs = str(step.get("logs") or "").strip()
    last = ""
    for line in reversed(logs.splitlines()):
        line = line.strip()
        if line and not line.startswith("실패했지만"):
            last = line
            break
    last = re.sub(r"^\[[^\]]*\]\s*", "", last)  # "[http] " 같은 머리말 빼기
    if not last:
        return "어떤 이유로 멈췄는지 기록이 남지 않았어요.", _GENERIC_FIX
    if last.startswith("예상하지 못한 오류"):
        return "예상하지 못한 오류로 멈췄어요.", _GENERIC_FIX
    parts = re.split(r"(?<=[.!?요])\s+", last, maxsplit=1)
    if len(parts) == 2 and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    return last, _GENERIC_FIX


def _branch_name(node: dict[str, Any] | None, data: dict[str, Any], matched: str) -> str:
    """조건 단계의 분기 id를 사람이 읽을 이름으로(조건 식이 짧으면 식을 보여 줌)."""
    for case in data.get("cases") or []:
        if str(case.get("id")) == matched:
            name = case.get("name") or case.get("label")
            if name:
                return str(name)
            when = case.get("when")
            if when:
                cleaned = re.sub(r"\{\{\s*[A-Za-z_][\w]*\.([\w]+)\s*\}\}", r"\1", str(when))
                return _short(cleaned)
    if matched == str(data.get("else") or "else"):
        return "그 밖의 경우"
    del node
    return matched


def _class_name(data: dict[str, Any], out: dict[str, Any]) -> str:
    name = out.get("class_name")
    if name:
        return str(name)
    cid = str(out.get("class_id") or "")
    for c in data.get("classes") or []:
        if str(c.get("id")) == cid:
            return str(c.get("name") or cid)
    return cid or "알 수 없음"


def _connector_target(data: dict[str, Any]) -> str:
    params = data.get("params")
    if not isinstance(params, dict):
        return ""
    for key in _TARGET_KEYS:
        value = params.get(key)
        if value and isinstance(value, str) and not _SECRET_HINT.search(key):
            if "{{" in value:  # 실행 때 정해지는 값이면 대상 이름을 못 씀
                continue
            return _short(value, 30)
    return ""


def _host(url: Any) -> str:
    try:
        host = urlparse(str(url)).hostname or ""
    except ValueError:
        host = ""
    return host or "외부 주소"


def _count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def describe_step(node: dict[str, Any] | None, step: dict[str, Any], label: str) -> str:
    """단계 하나를 한 문장으로. node는 그래프의 단계(dict), step은 step_dict 결과."""
    status = str(step.get("status") or "")
    ntype = str((node or {}).get("type") or "")
    data = _data(node, step)
    out = _out(step)
    took = _duration(step)
    name = label or "이름 없는"

    if status == "failed":
        problem, fix = failure_lines(step)
        return f"{name} 단계에서 문제가 생겼어요: {problem}\n{fix}"
    if status == "skipped":
        return f"{name} 단계는 꺼져 있어 건너뛰었어요."
    if status in ("running", "queued"):
        return f"{name} 단계를 실행하고 있어요."
    if status == "waiting_approval":
        if ntype in ("ask_person", "question"):
            return f"{name} 단계에서 담당자의 답을 기다리고 있어요."
        if ntype in ("assign_task", "assignment"):
            return f"{name} 단계에서 맡긴 일이 끝나기를 기다리고 있어요."
        return f"{name} 단계에서 담당자의 승인을 기다리고 있어요."

    if ntype == "input":
        keys = [k for k in out if not k.startswith("__") and k != "history"]
        # 영문 키 대신 화면에 보이는 항목 이름으로(예: currency → 통화)
        labels = {
            str(f.get("key")): str(f.get("label") or f.get("key"))
            for f in (data.get("fields") or [])
            if isinstance(f, dict) and f.get("key")
        }
        names = [labels.get(k, k) for k in keys]
        if names:
            return f"{name} 단계에서 {', '.join(names[:4])} 값을 받았어요."
        return f"{name} 단계에서 입력을 받았어요."
    if ntype == "question_classifier":
        return f"{name} 단계에서 '{_short(_class_name(data, out), 24)}'(으)로 판단했어요{took}."
    if ntype == "condition":
        matched = str(out.get("matched") or "")
        return f"{name} 단계에서 '{_branch_name(node, data, matched)}' 쪽으로 갔어요."
    if ntype == "llm":
        if data.get("output_schema") and out:
            keys = [k for k in out if k != "text"]
            shown = ", ".join(f"{k}={_short(out[k], 16)}" for k in keys[:3])
            if shown:
                return f"{name} 단계(AI)가 값을 정했어요: {shown}{took}."
        text = out.get("text")
        if text:
            return f'{name} 단계(AI)가 답을 만들었어요: "{_short(text)}"{took}.'
        return f"{name} 단계(AI)가 답을 만들었어요{took}."
    if ntype == "image_generate":
        n = int(out.get("count") or 0)
        return f"{name} 단계에서 이미지 {n}장을 만들었어요{took}."
    if ntype == "file_export":
        return f"{name} 단계에서 '{_short(out.get('filename') or '파일', 40)}' 파일을 만들었어요{took}."
    if ntype == "parameter_extractor":
        ok = out.get("__is_success")
        keys = [k for k in out if not k.startswith("__")]
        shown = ", ".join(f"{k}={_short(out[k], 16)}" for k in keys[:3])
        if ok is False:
            return f"{name} 단계에서 필요한 값을 다 찾지 못했어요{took}."
        return f"{name} 단계에서 값을 뽑았어요: {shown or '없음'}{took}."
    if ntype == "http":
        method = str(data.get("method") or "GET").upper()
        code = out.get("status")
        tail = f" → {code} 응답" if code is not None else ""
        return f"{name} 단계(외부 호출)가 {_host(data.get('url'))}에 {method} 요청{tail}{took}."
    if ntype == "mcp_tool":
        tool = str(data.get("tool") or "도구")
        if out.get("is_error"):
            return f"{name} 단계가 외부 도구 '{tool}'를 불렀지만 도구가 오류를 알려 줬어요{took}."
        return f"{name} 단계가 외부 도구(MCP) '{tool}'를 불러 결과를 받았어요{took}."
    if ntype == "api_tool":
        op = str(data.get("operation") or "도구")
        code = out.get("status")
        tail = f" → {code} 응답" if code is not None else ""
        return f"{name} 단계가 API 도구 '{op}'를 불렀어요{tail}{took}."
    if ntype == "connector":
        service = str(data.get("connector") or "서비스")
        action = str(data.get("action") or "")
        target = _connector_target(data)
        where = f" {target}(으)로" if target else ""
        what = f"({action})" if action else ""
        return f"{name} 단계(연결)가 {service}{what}{where} 보냈어요{took}."
    if ntype == "knowledge_search":
        results = out.get("results")
        n = _count(results)
        scores = [
            float(r["score"])
            for r in (results if isinstance(results, list) else [])
            if isinstance(r, dict) and isinstance(r.get("score"), (int, float))
        ]
        best = f", 최고 {max(scores):.2f}점" if scores else ""
        if n == 0:
            return f"{name} 단계(지식 검색)에서 맞는 문서를 찾지 못했어요{took}."
        return f"{name} 단계(지식 검색)가 자료 {n}개를 찾았어요({best.lstrip(', ') or '점수 없음'}){took}."
    if ntype == "approval":
        approved = out.get("approved")
        who = out.get("approver")
        by = f" ({_short(who, 20)})" if who else ""
        comment = out.get("comment")
        note = f' 의견: "{_short(comment, 30)}"' if comment else ""
        if approved is True:
            return f"{name} 단계에서 승인됐어요{by}.{note}".rstrip()
        if approved is False:
            return f"{name} 단계에서 반려됐어요{by}.{note}".rstrip()
        return f"{name} 단계(승인)를 지났어요."
    if ntype in ("ask_person", "question"):
        return f"{name} 단계에서 담당자가 답을 줬어요{took}."
    if ntype in ("assign_task", "assignment"):
        return f"{name} 단계에서 맡긴 일이 끝났어요{took}."
    if ntype == "data_table":
        op = str(data.get("operation") or "")
        if op in ("insert", "upsert"):
            return (
                f"{name} 단계(데이터 표)에 행을 {'추가' if op == 'insert' else '저장'}했어요{took}."
            )
        if op == "delete":
            return f"{name} 단계(데이터 표)에서 행을 지웠어요{took}."
        if op == "count":
            return f"{name} 단계(데이터 표)에서 행 {out.get('count', 0)}개를 셌어요{took}."
        if op in ("get", "find"):
            found = out.get("found")
            if found is False:
                return f"{name} 단계(데이터 표)에서 맞는 행을 찾지 못했어요{took}."
        n = _count(out.get("rows")) or (1 if out.get("row") else 0)
        return f"{name} 단계(데이터 표)에서 행 {n}개를 가져왔어요{took}."
    if ntype == "run_app":
        text = out.get("text")
        res = f': "{_short(text)}"' if text else ""
        return f"{name} 단계에서 다른 앱을 실행했어요{res}{took}."
    if ntype == "set_fields":
        keys = [k for k in out if not k.startswith("__")]
        return f"{name} 단계에서 값 {len(keys)}개를 정리했어요({', '.join(keys[:4])})."
    if ntype == "date_time":
        dt = out.get("result")
        return (
            f"{name} 단계(날짜·시간) 결과: {_short(dt, 30)}."
            if dt
            else f"{name} 단계(날짜·시간)를 마쳤어요."
        )
    if ntype == "wait":
        return f"{name} 단계에서 {out.get('waited_seconds', data.get('seconds', 0))}초 기다렸어요."
    if ntype == "iteration":
        return f"{name} 단계에서 항목 {out.get('count', _count(out.get('results')))}개를 하나씩 처리했어요{took}."
    if ntype == "loop":
        return f"{name} 단계에서 {out.get('iterations', 0)}번 되풀이했어요{took}."
    if ntype == "list_operator":
        return f"{name} 단계에서 목록을 다듬었어요(결과 {out.get('count', 0)}개)."
    if ntype in ("template", "variable_aggregator"):
        return f'{name} 단계에서 값을 엮었어요: "{_short(out.get("output", ""))}".'
    if ntype == "document_extractor":
        files = out.get("filenames")
        n = _count(files)
        return f"{name} 단계에서 파일 {n}개의 글을 읽었어요{took}."
    if ntype == "variable_assigner":
        keys = [k for k in out if not k.startswith("__")]
        return f"{name} 단계에서 대화 값 {len(keys)}개를 기억했어요."
    if ntype == "agent":
        n = _count(out.get("tool_calls"))
        return f"{name} 단계(에이전트)가 도구를 {n}번 쓰고 답을 만들었어요{took}."
    if ntype == "code":
        return f"{name} 단계(코드)를 실행했어요{took}."
    if ntype == "output":
        text = out.get("text")
        if text:
            return f'{name} 단계에서 결과를 냈어요: "{_short(text)}".'
        return f"{name} 단계에서 결과를 냈어요."
    return f"{name} 단계를 마쳤어요{took}."


def describe_run(run: dict[str, Any], steps: list[dict[str, Any]]) -> list[str]:
    """실행 전체를 문장 목록으로(단계 summary를 차례로 + 끝맺음)."""
    lines = [str(s.get("summary", "")) for s in steps if s.get("summary")]
    status = run.get("status")
    if status == "succeeded":
        lines.append("모든 단계를 마쳤어요.")
    elif status == "failed":
        lines.append("실행이 실패했어요. 문제가 생긴 단계를 확인하세요.")
    elif status == "waiting_approval":
        lines.append("사람의 확인을 기다리는 중이에요. 확인되면 이어서 실행돼요.")
    return lines
