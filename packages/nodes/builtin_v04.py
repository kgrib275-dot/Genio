"""v0.4 단계 5종(ADR 0008): 기다리기, 값 정리, 날짜·시간, 다른 앱 실행, 데이터 표.

n8n Wait·Edit Fields·Date & Time·Execute Workflow·Data Table에 해당한다. 기본 단계와 같은 NodeSpec 인터페이스.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nodes.spec import NodeContext, NodeError, NodeRegistry, NodeResult, NodeSpec

LABEL = {"type": "string", "title": "이름"}
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_WAIT_SECONDS = 300
DEFAULT_TZ = "Asia/Seoul"


# ---------------- wait ----------------
def _run_wait(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    try:
        seconds = float(data.get("seconds") or 0)
    except (TypeError, ValueError):
        raise NodeError("기다릴 시간(초)은 숫자로 적어 주세요.") from None
    if not 1 <= seconds <= MAX_WAIT_SECONDS:
        raise NodeError(f"기다리는 시간은 1초에서 {MAX_WAIT_SECONDS}초 사이로 정해 주세요.")
    ctx.log(f"{seconds:g}초 기다려요.")
    ctx.services.wait(seconds=seconds)
    return NodeResult(output={"waited_seconds": seconds})


WAIT = NodeSpec(
    type="wait",
    label="기다리기",
    category="흐름",
    description="정한 시간(1~300초)만큼 기다린 뒤 다음으로 넘어가요. 외부 서비스가 처리할 시간을 줄 때 써요.",
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            "seconds": {
                "type": "number",
                "title": "기다릴 시간(초)",
                "minimum": 1,
                "maximum": MAX_WAIT_SECONDS,
                "default": 5,
            },
        },
        "required": ["seconds"],
    },
    output_schema={"type": "object", "properties": {"waited_seconds": {"type": "number"}}},
    ui_schema={},
    run=_run_wait,
    outputs=lambda d: ["waited_seconds"],
)


# ---------------- set_fields ----------------
def _convert(value: Any, kind: str, key: str) -> Any:
    if kind == "number":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int | float):
            return value
        text = str(value).strip().replace(",", "")
        if text == "":
            return None
        try:
            num = float(text)
        except ValueError:
            raise NodeError(f"'{key}' 값 '{text[:30]}'을(를) 숫자로 바꿀 수 없어요.") from None
        return int(num) if num.is_integer() else num
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "y", "예", "네", "참", "on")
    if kind == "json":
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                raise NodeError(f"'{key}' 값이 JSON 형식이 아니에요.") from None
        return value
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _run_set_fields(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    out: dict[str, Any] = {}
    if data.get("keep_input"):
        source = ctx.render_value(data.get("source") or "")
        if isinstance(source, dict):
            out.update(source)
        elif source not in (None, ""):
            raise NodeError("'이어 받을 값'은 여러 값을 담은 묶음(객체)이어야 해요.")
    fields = data.get("fields") or []
    if not isinstance(fields, list) or not fields:
        raise NodeError("만들 값을 하나 이상 추가해 주세요.")
    for f in fields:
        if not isinstance(f, dict):
            continue
        key = str(f.get("key") or "").strip()
        if not KEY_RE.match(key):
            raise NodeError(
                f"값 이름 '{key}'은(는) 영문·숫자·밑줄로만 지어 주세요(숫자로 시작 불가)."
            )
        raw = ctx.render_value(f.get("value", ""))
        out[key] = _convert(raw, str(f.get("type") or "text"), key)
    return NodeResult(output=out)


def _set_fields_outputs(data: dict[str, Any]) -> list[str] | None:
    if data.get("keep_input"):
        return None  # 이어 받은 값은 미리 알 수 없다
    return [str(f.get("key")) for f in data.get("fields") or [] if isinstance(f, dict)]


SET_FIELDS = NodeSpec(
    type="set_fields",
    label="값 정리",
    category="데이터",
    description="앞 단계 값들로 새 값을 만들거나 이름을 바꿔 정리해요(글·숫자·참거짓·JSON). 다음 단계에서 쓰기 쉽게 다듬을 때 써요.",
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            "fields": {
                "type": "array",
                "title": "만들 값",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "title": "값 이름(영문)"},
                        "value": {"type": "string", "title": "값(예: {{n1.message}})"},
                        "type": {
                            "type": "string",
                            "title": "종류",
                            "enum": ["text", "number", "boolean", "json"],
                            "default": "text",
                        },
                    },
                    "required": ["key"],
                },
            },
            "keep_input": {
                "type": "boolean",
                "title": "앞 값 이어 받기",
                "default": False,
            },
            "source": {"type": "string", "title": "이어 받을 값(예: {{n2.body}})"},
        },
        "required": ["fields"],
    },
    output_schema={"type": "object"},
    ui_schema={},
    run=_run_set_fields,
    outputs=_set_fields_outputs,
)


# ---------------- date_time ----------------
UNITS = ("minutes", "hours", "days", "weeks", "months")
FORMATS = {
    "date": "%Y-%m-%d",
    "datetime": "%Y-%m-%d %H:%M",
    "korean": "%Y년 %m월 %d일",
    "korean_datetime": "%Y년 %m월 %d일 %H시 %M분",
    "time": "%H:%M",
}


def _tz(name: Any) -> ZoneInfo:
    try:
        return ZoneInfo(str(name or DEFAULT_TZ))
    except (ZoneInfoNotFoundError, ValueError):
        raise NodeError(f"시간대 '{name}'를 알 수 없어요. 예: Asia/Seoul") from None


def _parse_dt(value: Any, tz: ZoneInfo) -> datetime:
    if isinstance(value, int | float) and not isinstance(value, bool):
        ts = float(value) / (1000 if value > 1e11 else 1)
        return datetime.fromtimestamp(ts, tz=UTC).astimezone(tz)
    text = str(value or "").strip()
    if not text:
        raise NodeError("날짜·시간 값이 비어 있어요.")
    if re.fullmatch(r"\d{9,13}", text):
        return _parse_dt(int(text), tz)
    cleaned = text.replace("Z", "+00:00")
    for candidate in (cleaned, cleaned.replace(" ", "T", 1)):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)
        except ValueError:
            pass
    for fmt in ("%Y.%m.%d", "%Y/%m/%d", "%Y.%m.%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=tz)
        except ValueError:
            pass
    raise NodeError(
        f"'{text[:40]}'을(를) 날짜로 읽지 못했어요. 예: 2026-11-03 또는 2026-11-03 14:30"
    )


def _add_months(dt: datetime, months: int) -> datetime:
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    # 말일 보정(1월 31일 + 1개월 = 2월 말일)
    for day in (dt.day, 30, 29, 28):
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            continue
    return dt


def _fmt(dt: datetime, fmt: str | None) -> str:
    pattern = FORMATS.get(str(fmt or ""), str(fmt or "") or FORMATS["datetime"])
    try:
        return dt.strftime(pattern)
    except ValueError:
        raise NodeError("날짜 형식을 이해하지 못했어요. 예: %Y-%m-%d") from None


def _run_date_time(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    tz = _tz(data.get("timezone"))
    op = str(data.get("operation") or "now")
    fmt = data.get("format")
    if op == "now":
        dt = datetime.now(tz)
        return _dt_result(dt, _fmt(dt, fmt))
    value = ctx.render_value(data.get("value", ""))
    dt = _parse_dt(value, tz)
    if op == "format":
        return _dt_result(dt, _fmt(dt, fmt))
    if op == "add":
        try:
            amount = int(float(ctx.render_value(data.get("amount", 0)) or 0))
        except (TypeError, ValueError):
            raise NodeError("더할 양은 숫자로 적어 주세요(빼려면 음수).") from None
        unit = str(data.get("unit") or "days")
        if unit not in UNITS:
            raise NodeError("단위는 분·시간·일·주·개월 중에서 골라 주세요.")
        out = _add_months(dt, amount) if unit == "months" else dt + timedelta(**{unit: amount})
        return _dt_result(out, _fmt(out, fmt))
    if op == "diff":
        other = _parse_dt(ctx.render_value(data.get("other", "")), tz)
        unit = str(data.get("unit") or "days")
        seconds = (other - dt).total_seconds()
        per = {"minutes": 60, "hours": 3600, "days": 86400, "weeks": 604800, "months": 2629800}
        if unit not in per:
            raise NodeError("단위는 분·시간·일·주·개월 중에서 골라 주세요.")
        diff = seconds / per[unit]
        res = round(diff, 2)
        return NodeResult(
            output={
                "result": int(res) if float(res).is_integer() else res,
                "iso": other.isoformat(),
                "timestamp": int(other.timestamp()),
            }
        )
    raise NodeError("할 일을 '지금·형식 바꾸기·더하기·차이' 중에서 골라 주세요.")


def _dt_result(dt: datetime, text: str) -> NodeResult:
    return NodeResult(
        output={"result": text, "iso": dt.isoformat(), "timestamp": int(dt.timestamp())}
    )


DATE_TIME = NodeSpec(
    type="date_time",
    label="날짜·시간",
    category="데이터",
    description="지금 시각을 구하거나, 날짜 형식을 바꾸거나, 날짜에 기간을 더하거나, 두 날짜의 차이를 구해요.",
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            "operation": {
                "type": "string",
                "title": "할 일",
                "enum": ["now", "format", "add", "diff"],
                "default": "now",
            },
            "value": {"type": "string", "title": "날짜·시간(예: {{n1.date}})"},
            "format": {
                "type": "string",
                "title": "보여 줄 형식(date·datetime·korean·korean_datetime·time 또는 %Y-%m-%d)",
                "default": "datetime",
            },
            "amount": {"type": "string", "title": "더할 양(빼려면 음수)"},
            "unit": {"type": "string", "title": "단위", "enum": list(UNITS), "default": "days"},
            "other": {"type": "string", "title": "비교할 날짜(차이)"},
            "timezone": {"type": "string", "title": "시간대", "default": DEFAULT_TZ},
        },
        "required": ["operation"],
    },
    output_schema={
        "type": "object",
        "properties": {"result": {}, "iso": {"type": "string"}, "timestamp": {"type": "integer"}},
    },
    ui_schema={},
    run=_run_date_time,
    outputs=lambda d: ["result", "iso", "timestamp"],
)


# ---------------- run_app ----------------
def _run_run_app(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    app_id = str(data.get("app_id") or "").strip()
    if not app_id:
        raise NodeError("실행할 앱을 골라 주세요.")
    raw = data.get("input") or {}
    if not isinstance(raw, dict):
        raise NodeError("넘길 입력은 '이름: 값' 묶음으로 적어 주세요.")
    inputs = ctx.render_value(raw)
    out = ctx.services.run_app(app_id=app_id, inputs=inputs if isinstance(inputs, dict) else {})
    return NodeResult(output=out)


RUN_APP = NodeSpec(
    type="run_app",
    label="다른 앱 실행",
    category="흐름",
    description="이 워크스페이스의 다른 앱(저장한 최신 버전)을 하위 흐름으로 실행하고 결과를 받아 와요. 자주 쓰는 처리를 앱 하나로 만들어 여러 곳에서 다시 쓸 때 좋아요.",
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            "app_id": {"type": "string", "title": "실행할 앱"},
            "input": {"type": "object", "title": "넘길 입력(이름: 값)", "default": {}},
        },
        "required": ["app_id"],
    },
    output_schema={"type": "object", "properties": {"text": {"type": "string"}}},
    ui_schema={"app_id": {"ui:widget": "app"}, "input": {"ui:widget": "json"}},
    run=_run_run_app,
    outputs=None,  # 하위 앱의 출력 이름은 앱마다 다르다
)


# ---------------- data_table ----------------
TABLE_OPS = ["insert", "upsert", "get", "find", "list", "delete", "count"]


def _run_data_table(data: dict[str, Any], ctx: NodeContext) -> NodeResult:
    table_id = str(data.get("table_id") or "").strip()
    if not table_id:
        raise NodeError("쓸 데이터 표를 골라 주세요.")
    op = str(data.get("operation") or "")
    if op not in TABLE_OPS:
        raise NodeError("할 일을 추가·덮어쓰기·가져오기·찾기·목록·지우기·개수 중에서 골라 주세요.")
    key_raw = ctx.render_value(data.get("row_key") or "")
    row_key = str(key_raw).strip() if key_raw not in (None, "") else None
    rows_in = ctx.render_value(data.get("data") or {})
    filt = ctx.render_value(data.get("filter") or {})
    if not isinstance(rows_in, dict) or not isinstance(filt, dict):
        raise NodeError("값과 찾는 조건은 '이름: 값' 묶음으로 적어 주세요.")
    try:
        limit = int(data.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    out = ctx.services.data_table(
        table_id=table_id,
        operation=op,
        row_key=row_key,
        data=rows_in,
        filter=filt,
        limit=max(1, min(limit, 500)),
    )
    ctx.log(f"데이터 표 {op}: {out.get('count', 0)}건")
    return NodeResult(output=out)


DATA_TABLE = NodeSpec(
    type="data_table",
    label="데이터 표",
    category="데이터",
    description="워크스페이스의 데이터 표에 값을 저장하거나 찾아요(추가·키로 덮어쓰기·키로 가져오기·조건으로 찾기·목록·지우기·개수). 실행 사이에 값을 기억해야 할 때 써요.",
    input_schema={
        "type": "object",
        "properties": {
            "label": LABEL,
            "table_id": {"type": "string", "title": "데이터 표"},
            "operation": {
                "type": "string",
                "title": "할 일",
                "enum": TABLE_OPS,
                "default": "insert",
            },
            "row_key": {"type": "string", "title": "고유 키(덮어쓰기·가져오기·지우기)"},
            "data": {"type": "object", "title": "저장할 값(이름: 값)", "default": {}},
            "filter": {
                "type": "object",
                "title": "찾는 조건(이름: 값, 모두 같아야 함)",
                "default": {},
            },
            "limit": {
                "type": "integer",
                "title": "최대 개수",
                "default": 20,
                "minimum": 1,
                "maximum": 500,
            },
        },
        "required": ["table_id", "operation"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "row": {},
            "rows": {"type": "array"},
            "count": {"type": "integer"},
            "found": {"type": "boolean"},
        },
    },
    ui_schema={
        "table_id": {"ui:widget": "dataTable"},
        "data": {"ui:widget": "json"},
        "filter": {"ui:widget": "json"},
    },
    run=_run_data_table,
    outputs=lambda d: ["row", "rows", "count", "found"],
)


V04_SPECS = [WAIT, SET_FIELDS, DATE_TIME, RUN_APP, DATA_TABLE]


def register_v04(reg: NodeRegistry) -> None:
    for spec in V04_SPECS:
        if reg.get(spec.type) is None:
            reg.register(spec)
