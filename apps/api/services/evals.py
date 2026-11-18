"""평가 세트: 질문(입력)과 '이런 답이어야 해요' 조건을 모아 두고 한 번에 돌려 채점한다.

- 세트는 앱 설정(features.eval.cases)에 저장한다(마이그레이션 없음). 한 앱에 최대 50개.
- '한 번 돌리기'는 케이스마다 실행(trigger=eval)을 만들고, 같은 묶음 번호(run.context.eval.batch)로 묶는다.
- 채점은 규칙으로 한다(AI 심판 없음): 실행 성공, 꼭 들어갈 말, 들어가면 안 되는 말, 응답 시간, JSON 형식.
- 직전 묶음보다 통과율이 떨어지면 '점수가 떨어졌어요' 표시를 낸다(배포 전 확인용).
"""

import json
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.errors import AppError
from api.models import App, Run
from api.services.app_config import merged_features
from api.services.queue import enqueue_run

MAX_CASES = 50
MAX_TERMS = 10
HISTORY_SCAN = 600  # 평가 묶음을 모으려고 훑는 최근 평가 실행 수
EVAL_TRIGGER = "eval"


def _terms(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [x for x in raw.replace("\n", ",").split(",")]
    out: list[str] = []
    for t in raw or []:
        s = str(t).strip()[:200]
        if s and s not in out:
            out.append(s)
    return out[:MAX_TERMS]


def clean_case(raw: dict[str, Any]) -> dict[str, Any]:
    inp = raw.get("input")
    values: dict[str, Any] = {}
    for k, v in inp.items() if isinstance(inp, dict) else []:
        key = str(k).strip()[:60]
        if not key or len(values) >= 20:
            continue
        values[key] = v if isinstance(v, int | float | bool) else str(v)[:4000]
    try:
        max_s = float(raw.get("max_seconds") or 0)
    except (TypeError, ValueError):
        max_s = 0.0
    return {
        "id": str(raw.get("id") or "").strip()[:36] or uuid.uuid4().hex[:12],
        "name": str(raw.get("name") or "").strip()[:100] or "이름 없는 질문",
        "input": values,
        "contains": _terms(raw.get("contains")),
        "not_contains": _terms(raw.get("not_contains")),
        "max_seconds": max(0.0, min(max_s, 600.0)) or None,
        "json_valid": bool(raw.get("json_valid")),
    }


def get_cases(app: App) -> list[dict[str, Any]]:
    saved = (merged_features(app.features).get("eval") or {}).get("cases") or []
    return [clean_case(c) for c in saved if isinstance(c, dict)][:MAX_CASES]


def save_cases(db: Session, app: App, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(cases) > MAX_CASES:
        raise AppError(
            422,
            f"평가 질문은 한 앱에 {MAX_CASES}개까지 저장할 수 있어요.",
            "안 쓰는 질문을 지운 뒤 다시 저장하세요.",
        )
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in cases:
        item = clean_case(c)
        if item["id"] in seen:
            item["id"] = uuid.uuid4().hex[:12]
        seen.add(item["id"])
        cleaned.append(item)
    feats = dict(app.features or {})
    feats["eval"] = {"cases": cleaned}
    app.features = feats
    db.commit()
    return cleaned


# ---------------- 채점 ----------------
def _seconds(run: Run) -> float | None:
    if run.started_at and run.finished_at:
        return max(0.0, (run.finished_at - run.started_at).total_seconds())
    return None


def score_case(case: dict[str, Any], run: Run) -> dict[str, Any]:
    """규칙 채점. 검사 하나하나의 결과를 함께 돌려준다."""
    text = str((run.output or {}).get("text") or "")
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add(
        "실행 성공", run.status == "succeeded", run.error or "" if run.status != "succeeded" else ""
    )
    lowered = text.lower()
    for t in case.get("contains") or []:
        add(f"'{t}' 포함", t.lower() in lowered)
    for t in case.get("not_contains") or []:
        add(f"'{t}' 없음", t.lower() not in lowered)
    limit = case.get("max_seconds")
    took = _seconds(run)
    if limit:
        add(
            f"{limit:g}초 안에 답함",
            took is not None and took <= float(limit),
            f"{took:.1f}초" if took is not None else "",
        )
    if case.get("json_valid"):
        try:
            json.loads(text)
            add("JSON 형식", True)
        except ValueError:
            add("JSON 형식", False, "JSON으로 읽을 수 없어요")
    return {"passed": all(c["ok"] for c in checks), "checks": checks, "seconds": took}


# ---------------- 실행·결과 ----------------
def start(db: Session, app: App, user_id: str, graph: dict[str, Any]) -> dict[str, Any]:
    cases = get_cases(app)
    if not cases:
        raise AppError(
            422, "평가할 질문이 없어요.", "질문을 하나 이상 저장한 뒤 평가를 돌려 보세요."
        )
    batch = uuid.uuid4().hex[:12]
    runs: list[Run] = []
    for i, c in enumerate(cases):
        run = Run(
            app_id=app.id,
            trigger=EVAL_TRIGGER,
            input=dict(c["input"]),
            graph_snapshot=graph,
            created_by=user_id,
            context={"eval": {"batch": batch, "case": c["id"], "n": i}},
        )
        db.add(run)
        runs.append(run)
    db.commit()
    for run in runs:
        enqueue_run(run.id)
    return {"batch": batch, "total": len(runs)}


def _batch_runs(db: Session, app_id: str) -> dict[str, list[Run]]:
    rows = db.scalars(
        select(Run)
        .where(Run.app_id == app_id, Run.trigger == EVAL_TRIGGER)
        .order_by(Run.created_at.desc())
        .limit(HISTORY_SCAN)
    )
    groups: dict[str, list[Run]] = defaultdict(list)
    for r in rows:
        meta = (r.context or {}).get("eval") or {}
        if meta.get("batch"):
            groups[str(meta["batch"])].append(r)
    return groups


def _summarize(cases: dict[str, dict[str, Any]], runs: list[Run]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for r in sorted(runs, key=lambda x: int(((x.context or {}).get("eval") or {}).get("n", 0))):
        meta = (r.context or {}).get("eval") or {}
        case = cases.get(str(meta.get("case")), {"id": meta.get("case"), "name": "(지운 질문)"})
        finished = r.status in ("succeeded", "failed")
        scored = score_case(case, r) if finished else None
        results.append(
            {
                "run_id": r.id,
                "case_id": case.get("id"),
                "name": case.get("name"),
                "status": r.status,
                "finished": finished,
                "passed": scored["passed"] if scored else None,
                "checks": scored["checks"] if scored else [],
                "seconds": scored["seconds"] if scored else None,
                "answer": str((r.output or {}).get("text") or "")[:500],
                "cost": float(r.cost or 0),
            }
        )
    done = [x for x in results if x["finished"]]
    passed = sum(1 for x in done if x["passed"])
    secs = [x["seconds"] for x in done if x["seconds"] is not None]
    created = min((r.created_at for r in runs), default=None)
    return {
        "total": len(results),
        "finished": len(done),
        "passed": passed,
        "pass_rate": round(passed / len(done), 3) if done else None,
        "avg_seconds": round(sum(secs) / len(secs), 2) if secs else None,
        "cost": round(sum(x["cost"] for x in results), 6),
        "running": len(done) < len(results),
        "created_at": created,
        "results": results,
    }


def report(db: Session, app: App, batch: str) -> dict[str, Any]:
    runs = _batch_runs(db, app.id).get(batch)
    if not runs:
        raise AppError(404, "평가 결과를 찾을 수 없어요.", "평가 목록을 새로고침해 다시 고르세요.")
    cases = {c["id"]: c for c in get_cases(app)}
    return {"batch": batch, **_summarize(cases, runs)}


def history(db: Session, app: App, limit: int = 10) -> list[dict[str, Any]]:
    """최근 평가 묶음(새것 먼저). 직전 묶음보다 통과율이 떨어졌으면 dropped=True."""
    cases = {c["id"]: c for c in get_cases(app)}
    items: list[dict[str, Any]] = []
    for batch, runs in _batch_runs(db, app.id).items():
        s = _summarize(cases, runs)
        s.pop("results")
        items.append({"batch": batch, **s})
    items.sort(key=lambda x: x["created_at"] or datetime.min, reverse=True)
    items = items[:limit]
    for i, it in enumerate(items):
        prev = next((p for p in items[i + 1 :] if not p["running"]), None)
        it["dropped"] = bool(
            not it["running"]
            and prev is not None
            and it["pass_rate"] is not None
            and prev["pass_rate"] is not None
            and it["pass_rate"] < prev["pass_rate"]
        )
        it["previous_pass_rate"] = prev["pass_rate"] if prev else None
    return items
