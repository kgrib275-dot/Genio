"""실행 결과를 문장으로 설명한다(기능 정의서 S3).

예: "분류 단계에서 '결제 문의'로 판단했어요 (0.8초)". JSON은 화면에서 펼쳐 보기로만 보인다.
run_detail(routers/runs.py)이 이 함수들을 불러 각 단계에 summary, 실행 전체에 story를 붙인다.
"""

from typing import Any


def describe_step(node: dict[str, Any] | None, step: dict[str, Any], label: str) -> str:
    """단계 하나를 한 문장으로. node는 그래프의 노드(dict), step은 step_dict 결과."""
    del node
    status = step.get("status", "")
    if status == "failed":
        return f"{label} 단계에서 문제가 생겼어요."
    if status == "skipped":
        return f"{label} 단계는 꺼져 있어 건너뛰었어요."
    if status == "running":
        return f"{label} 단계를 실행하고 있어요."
    return f"{label} 단계를 마쳤어요."


def describe_run(run: dict[str, Any], steps: list[dict[str, Any]]) -> list[str]:
    """실행 전체를 문장 목록으로(단계 summary를 차례로 + 끝맺음)."""
    lines = [str(s.get("summary", "")) for s in steps if s.get("summary")]
    status = run.get("status")
    if status == "succeeded":
        lines.append("모든 단계를 마쳤어요.")
    elif status == "failed":
        lines.append("실행이 실패했어요.")
    return lines
