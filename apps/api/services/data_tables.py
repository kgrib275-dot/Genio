"""데이터 표(ADR 0008): 워크스페이스 안의 작은 표. 화면·API·흐름의 data_table 단계가 함께 쓴다."""

import csv
import io
import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.core.errors import AppError
from api.models import DataRow, DataTable

MAX_ROWS_PER_TABLE = 5000
MAX_ROW_BYTES = 32 * 1024
MAX_COLUMNS = 50
MAX_IMPORT_BYTES = 1024 * 1024
COLUMN_TYPES = ("text", "number", "boolean", "date", "json")
COLUMN_KEY_RE = re.compile(r"^[A-Za-z_가-힣][A-Za-z0-9_가-힣]{0,63}$")


def table_dict(t: DataTable, row_count: int) -> dict[str, Any]:
    return {
        "id": t.id,
        "workspace_id": t.workspace_id,
        "project_id": t.project_id,
        "name": t.name,
        "description": t.description,
        "columns": t.columns or [],
        "row_count": row_count,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def row_dict(r: DataRow) -> dict[str, Any]:
    return {
        "id": r.id,
        "table_id": r.table_id,
        "row_key": r.row_key,
        "data": r.data or {},
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


def row_count(db: Session, table_id: str) -> int:
    return int(
        db.scalar(select(func.count()).select_from(DataRow).where(DataRow.table_id == table_id))
        or 0
    )


def row_counts(db: Session, table_ids: list[str]) -> dict[str, int]:
    if not table_ids:
        return {}
    rows = db.execute(
        select(DataRow.table_id, func.count())
        .where(DataRow.table_id.in_(table_ids))
        .group_by(DataRow.table_id)
    ).all()
    return {tid: int(n) for tid, n in rows}


def clean_columns(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise AppError(422, "열 목록 형식이 맞지 않아요.", "열마다 이름(key)과 종류를 적어 주세요.")
    if len(raw) > MAX_COLUMNS:
        raise AppError(
            422, f"열은 {MAX_COLUMNS}개까지 만들 수 있어요.", "쓰지 않는 열을 지워 주세요."
        )
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in raw:
        if not isinstance(c, dict):
            continue
        key = str(c.get("key") or "").strip()
        if not COLUMN_KEY_RE.match(key):
            raise AppError(
                422,
                f"열 이름 '{key[:30]}'을(를) 쓸 수 없어요.",
                "글자·숫자·밑줄로 64자 이내, 숫자로 시작하지 않게 지어 주세요.",
            )
        if key in seen:
            raise AppError(422, f"'{key}' 열이 두 번 있어요.", "열 이름은 서로 달라야 해요.")
        seen.add(key)
        kind = str(c.get("type") or "text")
        if kind not in COLUMN_TYPES:
            raise AppError(
                422,
                f"'{key}' 열의 종류를 알 수 없어요.",
                "글·숫자·참거짓·날짜·JSON 중에서 골라 주세요.",
            )
        out.append({"key": key, "label": str(c.get("label") or key)[:100], "type": kind})
    return out


def _coerce(value: Any, kind: str) -> Any:
    if value is None or value == "":
        return value
    if kind == "number":
        if isinstance(value, int | float) and not isinstance(value, bool):
            return value
        try:
            num = float(str(value).replace(",", "").strip())
        except ValueError:
            return value
        return int(num) if num.is_integer() else num
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "y", "예", "네", "참", "on")
    if kind == "json" and isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    if kind in ("text", "date") and not isinstance(value, str):
        return value if isinstance(value, dict | list) else str(value)
    return value


def clean_data(table: DataTable, data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise AppError(422, "값은 '이름: 값' 묶음이어야 해요.", '예: {"name": "홍길동"}')
    types = {c["key"]: c["type"] for c in table.columns or []}
    out = {str(k)[:64]: _coerce(v, types.get(str(k), "")) for k, v in data.items()}
    size = len(json.dumps(out, ensure_ascii=False, default=str).encode("utf-8"))
    if size > MAX_ROW_BYTES:
        raise AppError(
            413,
            "한 줄에 담은 값이 너무 커요(32KB 초과).",
            "긴 글은 지식베이스나 파일로 옮겨 주세요.",
        )
    return out


def clean_key(row_key: Any) -> str | None:
    if row_key is None:
        return None
    key = str(row_key).strip()
    if not key:
        return None
    if len(key) > 200:
        raise AppError(
            422, "고유 키가 너무 길어요(200자 초과).", "짧은 id나 이메일 같은 값을 쓰세요."
        )
    return key


def _ensure_room(db: Session, table: DataTable, adding: int = 1) -> None:
    if row_count(db, table.id) + adding > MAX_ROWS_PER_TABLE:
        raise AppError(
            409,
            f"표 하나에는 {MAX_ROWS_PER_TABLE}줄까지 담을 수 있어요.",
            "오래된 줄을 지우거나 새 표를 만들어 주세요.",
        )


def find_by_key(db: Session, table_id: str, row_key: str) -> DataRow | None:
    return db.scalar(
        select(DataRow).where(DataRow.table_id == table_id, DataRow.row_key == row_key)
    )


def insert_row(db: Session, table: DataTable, row_key: Any, data: Any) -> DataRow:
    key = clean_key(row_key)
    values = clean_data(table, data)
    if key is not None and find_by_key(db, table.id, key) is not None:
        raise AppError(
            409,
            f"'{key[:40]}' 키를 가진 줄이 이미 있어요.",
            "다른 키를 쓰거나 그 줄을 고쳐 주세요.",
        )
    _ensure_room(db, table)
    row = DataRow(table_id=table.id, row_key=key, data=values)
    db.add(row)
    db.flush()
    return row


def upsert_row(db: Session, table: DataTable, row_key: Any, data: Any) -> tuple[DataRow, bool]:
    """키로 찾아 값을 합치고, 없으면 새로 만든다. (줄, 새로 만들었는지)"""
    key = clean_key(row_key)
    if key is None:
        raise AppError(422, "덮어쓰려면 고유 키가 필요해요.", "단계의 '고유 키' 칸을 채워 주세요.")
    values = clean_data(table, data)
    row = find_by_key(db, table.id, key)
    if row is None:
        _ensure_room(db, table)
        row = DataRow(table_id=table.id, row_key=key, data=values)
        db.add(row)
        db.flush()
        return row, True
    row.data = {**(row.data or {}), **values}
    db.flush()
    return row, False


def _match(row: DataRow, filt: dict[str, Any]) -> bool:
    data = row.data or {}
    for k, v in filt.items():
        if k == "row_key":
            if str(row.row_key or "") != str(v):
                return False
            continue
        if str(data.get(k, "")) != str(v if v is not None else ""):
            return False
    return True


def all_rows(db: Session, table_id: str) -> list[DataRow]:
    return list(
        db.scalars(
            select(DataRow)
            .where(DataRow.table_id == table_id)
            .order_by(DataRow.created_at.desc(), DataRow.id)
        )
    )


def search_rows(
    db: Session, table_id: str, q: str | None, limit: int, offset: int
) -> tuple[int, list[DataRow]]:
    rows = all_rows(db, table_id)
    if q and q.strip():
        needle = q.strip().lower()
        rows = [
            r
            for r in rows
            if needle in (r.row_key or "").lower()
            or needle in json.dumps(r.data or {}, ensure_ascii=False, default=str).lower()
        ]
    return len(rows), rows[offset : offset + limit]


def run_operation(
    db: Session,
    table: DataTable,
    *,
    operation: str,
    row_key: str | None,
    data: dict[str, Any] | None,
    filter: dict[str, Any] | None,
    limit: int,
) -> dict[str, Any]:
    """흐름 단계용. 결과 형식은 늘 {row, rows, count, found}."""
    filt = {str(k): v for k, v in (filter or {}).items()}
    if operation == "insert":
        row = insert_row(db, table, row_key, data or {})
        db.commit()
        return {"row": row_dict_lite(row), "rows": [], "count": 1, "found": True}
    if operation == "upsert":
        row, _ = upsert_row(db, table, row_key, data or {})
        db.commit()
        return {"row": row_dict_lite(row), "rows": [], "count": 1, "found": True}
    if operation == "get":
        key = clean_key(row_key)
        if key is None:
            raise AppError(
                422, "가져오려면 고유 키가 필요해요.", "단계의 '고유 키' 칸을 채워 주세요."
            )
        got = find_by_key(db, table.id, key)
        return {
            "row": row_dict_lite(got) if got else None,
            "rows": [],
            "count": 1 if got else 0,
            "found": got is not None,
        }
    rows = all_rows(db, table.id)
    if operation in ("find", "list", "count", "delete"):
        if operation != "list" and row_key:
            filt["row_key"] = row_key
        matched = [r for r in rows if _match(r, filt)] if filt else rows
        if operation == "count":
            return {"row": None, "rows": [], "count": len(matched), "found": bool(matched)}
        if operation == "delete":
            if not filt:
                raise AppError(
                    422,
                    "무엇을 지울지 정하지 않았어요.",
                    "고유 키나 찾는 조건을 채워 주세요(전체 지우기는 화면에서만 할 수 있어요).",
                )
            for r in matched[:limit]:
                db.delete(r)
            db.commit()
            n = min(len(matched), limit)
            return {"row": None, "rows": [], "count": n, "found": n > 0}
        picked = matched[:limit]
        return {
            "row": row_dict_lite(picked[0]) if picked else None,
            "rows": [row_dict_lite(r) for r in picked],
            "count": len(picked),
            "found": bool(picked),
        }
    raise AppError(
        422,
        "알 수 없는 할 일이에요.",
        "추가·덮어쓰기·가져오기·찾기·목록·지우기·개수 중에서 고르세요.",
    )


def row_dict_lite(r: DataRow) -> dict[str, Any]:
    """흐름에 넘기는 줄: 값 + row_key."""
    return {**(r.data or {}), "row_key": r.row_key}


# ---------------- CSV ----------------
def import_csv(db: Session, table: DataTable, content: bytes) -> dict[str, Any]:
    if len(content) > MAX_IMPORT_BYTES:
        raise AppError(413, "CSV 파일이 너무 커요(1MB 초과).", "나눠서 여러 번 가져오세요.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("cp949")
        except UnicodeDecodeError:
            raise AppError(
                422, "CSV 파일의 글자를 읽지 못했어요.", "UTF-8로 저장한 CSV를 올려 주세요."
            ) from None
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise AppError(422, "CSV 파일이 비어 있어요.", "첫 줄에 열 이름을 적어 주세요.") from None
    header = [h.strip() for h in header]
    if not any(header):
        raise AppError(422, "CSV 첫 줄에 열 이름이 없어요.", "첫 줄에 열 이름을 적어 주세요.")
    key_idx = next((i for i, h in enumerate(header) if h.lower() in ("row_key", "키")), None)
    cols = list(table.columns or [])
    known = {c["key"] for c in cols}
    for i, h in enumerate(header):
        if i == key_idx or not h or h in known:
            continue
        if not COLUMN_KEY_RE.match(h):
            raise AppError(
                422,
                f"CSV 열 이름 '{h[:30]}'을(를) 쓸 수 없어요.",
                "글자·숫자·밑줄로 지어 주세요(숫자로 시작 불가).",
            )
        cols.append({"key": h, "label": h, "type": "text"})
        known.add(h)
    if len(cols) > MAX_COLUMNS:
        raise AppError(422, f"열은 {MAX_COLUMNS}개까지 만들 수 있어요.", "CSV 열 수를 줄여 주세요.")
    table.columns = cols
    records = [r for r in reader if any(cell.strip() for cell in r)]
    _ensure_room(db, table, len(records))
    imported = 0
    for rec in records:
        data = {
            h: rec[i] if i < len(rec) else "" for i, h in enumerate(header) if h and i != key_idx
        }
        key = rec[key_idx].strip() if key_idx is not None and key_idx < len(rec) else None
        if key:
            upsert_row(db, table, key, data)
        else:
            insert_row(db, table, None, data)
        imported += 1
    db.commit()
    return {"imported": imported, "columns": cols}


def export_csv(db: Session, table: DataTable) -> str:
    rows = all_rows(db, table.id)
    keys = [c["key"] for c in table.columns or []]
    for r in rows:
        for k in r.data or {}:
            if k not in keys:
                keys.append(k)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["row_key", *keys])
    for r in reversed(rows):
        vals = []
        for k in keys:
            v = (r.data or {}).get(k, "")
            vals.append(json.dumps(v, ensure_ascii=False) if isinstance(v, dict | list) else v)
        w.writerow([r.row_key or "", *vals])
    return "﻿" + buf.getvalue()
