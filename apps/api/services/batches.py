"""v0.8 일괄 실행: 표(CSV·XLSX)의 줄마다 흐름을 한 번씩 실행하고 결과를 표로 돌려준다.

저장: 새 테이블 없이 줄마다 Run 한 개(trigger="batch")를 미리 만들어 두고, 일괄 실행 번호(batch_id)·줄 번호·
보냈는지(dispatched) 같은 표시는 run.context에 둔다. 상태는 모두 DB에 있어 서버가 다시 켜져도 이어진다.

진행: 한 번에 CONCURRENCY(5)줄씩만 큐에 넣는다. 줄이 끝날 때마다 executor가 advance_batch를 불러 다음 줄을 넣고,
화면이 상태를 물을 때도 한 번 더 밀어 준다(알림을 놓쳐도 멈추지 않게).
"""

import csv
import io
import re
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from api.core.errors import AppError
from api.models import App, Run, WorkflowVersion
from api.services.chat import input_fields

MAX_ROWS_APP = 200
MAX_ROWS_PUBLIC = 50
MAX_ACTIVE_PUBLIC_BATCHES = 3
CONCURRENCY = 5
MAX_FILE_BYTES = 2 * 1024 * 1024
STUCK_AFTER = timedelta(minutes=5)

STATUS_LABEL = {
    "queued": "대기",
    "running": "실행 중",
    "succeeded": "성공",
    "failed": "실패",
    "cancelled": "취소",
    "waiting_approval": "승인 대기",
}
SETTLED = {"succeeded", "failed", "cancelled", "waiting_approval"}

_guard = threading.local()


# ---------------- 입력 칸·파일 읽기 ----------------
def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


def batch_fields(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """일괄 실행에 쓸 입력 칸. 파일 칸이 있으면 쓸 수 없다."""
    fields = input_fields(graph)
    if any(f["type"] == "file" for f in fields):
        raise AppError(
            422,
            "파일 입력 칸이 있는 흐름은 일괄 실행을 쓸 수 없어요.",
            "파일 칸을 뺀 흐름에서 쓰거나, 한 건씩 실행하세요.",
        )
    if not fields:
        raise AppError(
            422,
            "입력 칸이 없는 흐름은 일괄 실행이 필요 없어요.",
            "입력 단계에 칸을 추가하거나, 바로 한 번 실행하세요.",
        )
    return fields


def template_csv(fields: list[dict[str, Any]]) -> bytes:
    """엑셀에서 바로 열리는 CSV 양식(UTF-8 BOM). 머리글은 입력 칸 이름."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f["label"] or f["key"] for f in fields])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise AppError(
        422,
        "파일의 글자를 읽지 못했어요.",
        "엑셀에서 'CSV UTF-8'로 저장하거나 XLSX 파일로 다시 올려 주세요.",
    )


def _read_table(filename: str, content: bytes) -> list[list[str]]:
    name = (filename or "").lower()
    if len(content) > MAX_FILE_BYTES:
        raise AppError(413, "파일이 너무 커요(최대 2MB).", "줄 수를 줄이거나 나눠서 올려 주세요.")
    if name.endswith(".xlsx"):
        try:
            from openpyxl import load_workbook

            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            ws = wb.worksheets[0]
            return [
                ["" if c is None else str(c).strip() for c in row]
                for row in ws.iter_rows(values_only=True)
            ]
        except AppError:
            raise
        except Exception:
            raise AppError(
                422,
                "엑셀 파일을 읽지 못했어요.",
                "파일이 깨지지 않았는지 확인하고 다시 올려 주세요.",
            ) from None
    if name.endswith((".csv", ".txt", ".tsv")):
        body = _decode(content)
        try:
            dialect = csv.Sniffer().sniff(body[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return [[c.strip() for c in row] for row in csv.reader(io.StringIO(body), dialect)]
    raise AppError(
        415,
        "CSV나 XLSX 파일만 올릴 수 있어요.",
        "양식 내려받기로 받은 파일에 내용을 채워 올려 주세요.",
    )


def _coerce(field: dict[str, Any], raw: Any) -> tuple[Any, dict[str, str] | None]:
    """칸 하나의 값을 맞추고, 문제가 있으면 두 줄 오류를 돌려준다."""
    label = field["label"] or field["key"]
    s = "" if raw is None else str(raw).strip()
    if s == "":
        if field["required"]:
            return None, {
                "message": f"'{label}' 칸이 비어 있어요.",
                "hint": "그 칸을 채운 뒤 다시 올려 주세요.",
            }
        return None, None
    if field["type"] == "number":
        try:
            num = float(s.replace(",", ""))
        except ValueError:
            return None, {
                "message": f"'{label}'에는 숫자를 넣어 주세요(지금 '{s[:20]}').",
                "hint": "숫자만 적어 다시 올려 주세요.",
            }
        return (int(num) if num.is_integer() else num), None
    if len(s) > 4000:
        return None, {
            "message": f"'{label}' 글이 너무 길어요(4,000자 넘음).",
            "hint": "내용을 줄여서 다시 올려 주세요.",
        }
    return s, None


def validate_values(
    fields: list[dict[str, Any]], values: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    clean: dict[str, Any] = {}
    errors: list[dict[str, str]] = []
    for f in fields:
        v, err = _coerce(f, values.get(f["key"]))
        if err:
            errors.append(err)
        elif v is not None:
            clean[f["key"]] = v
    return clean, errors


def parse_upload(
    filename: str, content: bytes, fields: list[dict[str, Any]], max_rows: int
) -> dict[str, Any]:
    """올린 표를 읽어 열을 입력 칸에 맞추고, 줄마다 값과 오류를 돌려준다(미리 보기용)."""
    table = [r for r in _read_table(filename, content)]
    if not table or not any(c for c in table[0]):
        raise AppError(
            422, "표의 첫 줄(머리글)이 비어 있어요.", "양식 내려받기로 받은 파일을 써 주세요."
        )
    header = table[0]
    by_name: dict[str, dict[str, Any]] = {}
    for f in fields:
        by_name[_norm(f["key"])] = f
        by_name[_norm(f["label"])] = f
    columns: list[dict[str, Any]] = []
    index: dict[str, int] = {}
    for i, h in enumerate(header):
        hit = by_name.get(_norm(h))
        columns.append({"header": h, "field": hit["key"] if hit else None})
        if hit and hit["key"] not in index:
            index[hit["key"]] = i
    missing = [f["label"] for f in fields if f["required"] and f["key"] not in index]
    if missing:
        raise AppError(
            422,
            f"필수 칸 열이 없어요: {', '.join(missing)}.",
            "양식 내려받기로 받은 머리글 그대로 두고 다시 올려 주세요.",
        )
    rows: list[dict[str, Any]] = []
    for n, raw in enumerate(table[1:], start=2):
        if not any(str(c).strip() for c in raw):
            continue
        values = {k: (raw[i] if i < len(raw) else "") for k, i in index.items()}
        clean, errors = validate_values(fields, values)
        rows.append({"row": n, "values": clean, "errors": errors})
    if not rows:
        raise AppError(422, "실행할 줄이 없어요.", "머리글 아래에 값을 한 줄 이상 채워 주세요.")
    if len(rows) > max_rows:
        raise AppError(
            422,
            f"한 번에 {max_rows}건까지 실행할 수 있어요(지금 {len(rows)}건).",
            "파일을 나눠서 올려 주세요.",
        )
    return {
        "columns": columns,
        "unmatched": [c["header"] for c in columns if c["field"] is None and c["header"]],
        "rows": rows,
        "total": len(rows),
        "ok_count": sum(1 for r in rows if not r["errors"]),
        "error_count": sum(1 for r in rows if r["errors"]),
    }


# ---------------- 만들기·읽기 ----------------
def graph_ref(
    db: Session, app: App, version_id: str | None
) -> tuple[str | None, dict[str, Any] | None]:
    """줄마다 그래프를 복사하지 않도록, 저장한 최신 버전과 같으면 그 버전을 가리킨다."""
    if version_id:
        return version_id, None
    graph = app.draft_graph or {}
    latest = db.scalar(
        select(WorkflowVersion)
        .where(WorkflowVersion.app_id == app.id)
        .order_by(WorkflowVersion.version.desc())
        .limit(1)
    )
    if latest is not None and latest.graph == graph:
        return latest.id, None
    return None, graph


def create_batch(
    db: Session,
    app: App,
    *,
    rows: list[dict[str, Any]],
    fields: list[dict[str, Any]],
    version_id: str | None,
    snapshot: dict[str, Any] | None,
    user_id: str | None,
    source: str,
    max_rows: int,
    skip_invalid: bool = False,
) -> tuple[str, int]:
    """줄마다 Run을 만들고 첫 몇 줄을 큐에 넣는다. (batch_id, 줄 수)."""
    if not rows:
        raise AppError(422, "실행할 줄이 없어요.", "미리 보기에서 줄을 확인한 뒤 실행하세요.")
    if len(rows) > max_rows:
        raise AppError(
            422,
            f"한 번에 {max_rows}건까지 실행할 수 있어요(지금 {len(rows)}건).",
            "줄 수를 줄여서 다시 실행하세요.",
        )
    prepared: list[tuple[int, dict[str, Any]]] = []
    bad: list[dict[str, Any]] = []
    for i, r in enumerate(rows, start=1):
        clean, errors = validate_values(fields, dict(r.get("values") or {}))
        n = int(r.get("row") or i + 1)
        if errors:
            bad.append({"row": n, "errors": errors})
            continue
        prepared.append((n, clean))
    if bad and not skip_invalid:
        first = bad[0]["errors"][0]
        raise AppError(
            422,
            f"{len(bad)}줄에 고칠 값이 있어요. 첫 오류: {first['message']}",
            "고친 뒤 다시 올리거나, 오류 줄을 빼고 실행하세요.",
        )
    if not prepared:
        raise AppError(422, "실행할 수 있는 줄이 없어요.", "값을 고친 뒤 다시 올려 주세요.")
    batch_id = uuid.uuid4().hex
    now = datetime.now(UTC).isoformat()
    for n, values in prepared:
        db.add(
            Run(
                app_id=app.id,
                version_id=version_id,
                graph_snapshot=snapshot,
                trigger="batch",
                status="queued",
                input=values,
                context={
                    "batch_id": batch_id,
                    "row": n,
                    "source": source,
                    "dispatched": False,
                    "created": now,
                },
                created_by=user_id,
            )
        )
    db.commit()
    advance_batch(db, app.id, batch_id)
    return batch_id, len(prepared)


def _runs(db: Session, app_id: str, batch_id: str) -> list[Run]:
    rows = db.scalars(
        select(Run).where(
            Run.app_id == app_id,
            Run.trigger == "batch",
            Run.context["batch_id"].as_string() == batch_id,
        )
    )
    return sorted(rows, key=lambda r: int((r.context or {}).get("row") or 0))


def row_status(run: Run) -> str:
    ctx = run.context or {}
    if run.status == "failed" and ctx.get("cancelled"):
        return "cancelled"
    return run.status


def advance_batch(db: Session, app_id: str, batch_id: str) -> int:
    """아직 큐에 넣지 않은 줄을 동시 실행 한도까지 큐에 넣는다. 넣은 줄 수를 돌려준다."""
    from api.config import get_settings
    from api.services.queue import enqueue_run

    if getattr(_guard, "active", False):
        return 0  # 바로 실행 모드에서 줄이 끝날 때 다시 들어오는 경우: 바깥 반복이 이어서 처리
    _guard.active = True
    sent = 0
    try:
        while True:
            picked = _claim(db, app_id, batch_id)
            if not picked:
                break
            sent += len(picked)
            for rid in picked:
                enqueue_run(rid)
            if not get_settings().genio_run_inline:
                break
    finally:
        _guard.active = False
    return sent


def _claim(db: Session, app_id: str, batch_id: str) -> list[str]:
    """한도 안에서 다음 줄을 '보냄'으로 표시하고 id를 돌려준다(여러 워커가 동시에 불러도 겹치지 않게 잠금)."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("select pg_advisory_xact_lock(hashtext(:k))"), {"k": f"genio-batch-{batch_id}"}
        )
    runs = _runs(db, app_id, batch_id)
    active = sum(
        1 for r in runs if (r.context or {}).get("dispatched") and r.status in ("queued", "running")
    )
    room = CONCURRENCY - active
    out: list[str] = []
    for r in runs:
        if room <= 0:
            break
        ctx = dict(r.context or {})
        if r.status == "queued" and not ctx.get("dispatched") and not ctx.get("cancelled"):
            ctx["dispatched"] = True
            ctx["dispatched_at"] = datetime.now(UTC).isoformat()
            r.context = ctx
            out.append(r.id)
            room -= 1
    db.commit()
    return out


def _nudge_stuck(db: Session, runs: list[Run]) -> None:
    """보냈는데 5분 넘게 '대기'에 머무는 줄(워커가 끊긴 경우)은 다시 큐에 넣는다."""
    from api.services.queue import enqueue_run

    now = datetime.now(UTC)
    for r in runs:
        ctx = r.context or {}
        if r.status != "queued" or not ctx.get("dispatched"):
            continue
        try:
            at = datetime.fromisoformat(str(ctx.get("dispatched_at")))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        if now - at > STUCK_AFTER:
            ctx = {**ctx, "dispatched_at": now.isoformat()}
            r.context = ctx
            db.commit()
            enqueue_run(r.id)


def _makes_files(db: Session, run: Run) -> bool:
    """이 일괄 실행의 흐름에 파일을 만드는 단계(이미지·파일 만들기)가 있는지."""
    from api.engine.executor import load_graph

    try:
        return any(
            n.type in ("image_generate", "file_export") and not n.disabled
            for n in load_graph(db, run).nodes
        )
    except Exception:
        return False


def batch_status(
    db: Session,
    app_id: str,
    batch_id: str,
    *,
    public: bool,
    origin: str = "",
    token: str = "",
) -> dict[str, Any]:
    """진행 상황과 줄별 결과. 공개 화면에는 내부 값(실행 번호·원문 오류)을 빼고 보낸다.

    파일을 만드는 흐름이면 줄마다 `files`를 붙인다. 로그인한 화면은 실행 기록 주소를, 공유 링크는
    서명된 내려받기 주소(24시간)를 쓴다.
    """
    runs = _runs(db, app_id, batch_id)
    if not runs:
        raise AppError(
            404, "일괄 실행을 찾을 수 없어요.", "주소가 맞는지 확인하거나 새로 실행하세요."
        )
    advance_batch(db, app_id, batch_id)  # 알림을 놓쳤을 때를 위한 한 번 더 밀기
    runs = _runs(db, app_id, batch_id)
    _nudge_stuck(db, runs)
    counts = {k: 0 for k in STATUS_LABEL}
    rows: list[dict[str, Any]] = []
    with_files = _makes_files(db, runs[0])
    app = db.get(App, app_id) if with_files else None
    for r in runs:
        st = row_status(r)
        counts[st] = counts.get(st, 0) + 1
        out = r.output or {}
        item: dict[str, Any] = {
            "row": int((r.context or {}).get("row") or 0),
            "status": st,
            "input": r.input,
            "text": str(out.get("text", "")) if st == "succeeded" else "",
        }
        if st == "failed":
            item["error"] = (
                {
                    "message": "이 줄은 실행하지 못했어요.",
                    "hint": "입력을 확인하고 다시 실행하거나, 앱을 만든 사람에게 알려 주세요.",
                }
                if public
                else {"message": (r.error or "실행하지 못했어요.")[:500], "hint": ""}
            )
        if not public:
            item["run_id"] = r.id
        if with_files and app is not None and st == "succeeded":
            from api.services import run_files

            made = run_files.files_of_run(db, r, app.workspace_id)
            if made:
                shown = run_files.with_public_links(made, app_id, r.id) if public else made
                item["files"] = [
                    {
                        "id": f["id"],
                        "filename": f["filename"],
                        "kind": f["kind"],
                        "url": (
                            run_files.public_url(origin, token, f)
                            if public and origin and token
                            else (f"{origin}/runs/{r.id}" if origin and not public else "")
                        ),
                    }
                    for f in shown
                ]
        rows.append(item)
    settled = sum(counts[k] for k in SETTLED)
    cancelled = any((r.context or {}).get("cancelled") for r in runs)
    return {
        "batch_id": batch_id,
        "total": len(runs),
        "counts": counts,
        "settled": settled,
        "done": settled == len(runs),
        "cancelled": cancelled,
        "created_at": runs[0].created_at,
        "rows": rows,
    }


def cancel_batch(db: Session, app_id: str, batch_id: str) -> int:
    """아직 시작하지 않은 줄을 취소한다. 이미 도는 줄은 끝까지 간다. 취소한 줄 수."""
    runs = _runs(db, app_id, batch_id)
    if not runs:
        raise AppError(
            404, "일괄 실행을 찾을 수 없어요.", "주소가 맞는지 확인하거나 새로 실행하세요."
        )
    n = 0
    for r in runs:
        ctx = dict(r.context or {})
        if r.status == "queued":
            ctx["cancelled"] = True
            r.context = ctx
            r.status = "failed"
            r.error = "일괄 실행을 취소해서 실행하지 않았어요."
            r.finished_at = datetime.now(UTC)
            n += 1
    db.commit()
    return n


def active_public_batches(db: Session, app_id: str) -> int:
    """아직 끝나지 않은 공개 일괄 실행 수(비용 폭주를 막는 한도용)."""
    rows = db.scalars(
        select(Run).where(
            Run.app_id == app_id,
            Run.trigger == "batch",
            Run.status.in_(("queued", "running")),
        )
    )
    ids = {
        str((r.context or {}).get("batch_id"))
        for r in rows
        if (r.context or {}).get("source") == "public"
    }
    return len(ids)


def on_run_finished(db: Session, run: Run) -> None:
    """executor가 줄 하나를 마칠 때 부른다: 다음 줄을 큐에 넣는다."""
    ctx = run.context or {}
    batch_id = ctx.get("batch_id")
    if run.trigger == "batch" and batch_id:
        advance_batch(db, run.app_id, str(batch_id))


# ---------------- 결과 CSV ----------------
def _csv_safe(v: Any) -> str:
    """엑셀에서 수식으로 실행되지 않게 =, +, -, @로 시작하는 글 앞에 작은따옴표를 붙인다."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def batch_input_fields(db: Session, app_id: str, batch_id: str) -> list[dict[str, Any]]:
    """그 일괄 실행이 쓴 그래프(저장 버전 또는 복사본)의 입력 칸. 그 뒤에 흐름을 고쳐도 결과 표 머리글이 맞게."""
    from api.engine.executor import load_graph

    runs = _runs(db, app_id, batch_id)
    if not runs:
        return []
    try:
        return input_fields(load_graph(db, runs[0]).dump())
    except Exception:
        return []


def results_csv(status: dict[str, Any], fields: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    has_files = any(r.get("files") for r in status["rows"])
    w.writerow(
        [
            "줄",
            "상태",
            *[f["label"] or f["key"] for f in fields],
            "결과",
            *(["파일"] if has_files else []),
            "오류",
        ]
    )
    for r in status["rows"]:
        err = ""
        if r.get("error"):
            e = r["error"]
            err = f"{e['message']} {e['hint']}".strip()
        w.writerow(
            [
                r["row"],
                STATUS_LABEL.get(r["status"], r["status"]),
                *[_csv_safe((r["input"] or {}).get(f["key"], "")) for f in fields],
                _csv_safe(r["text"]),
                *(
                    [
                        _csv_safe(
                            "\n".join(
                                f"{f['filename']} {f['url']}".strip() for f in r.get("files") or []
                            )
                        )
                    ]
                    if has_files
                    else []
                ),
                _csv_safe(err),
            ]
        )
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
