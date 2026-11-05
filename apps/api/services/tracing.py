"""외부 추적(v0.6, v0.9 확대 — ADR 0010·0013): 끝난 실행을 여러 추적 서비스로 보낸다.

서비스: Langfuse, LangSmith, OpenTelemetry(OTLP/HTTP), Arize Phoenix, Arize AX, Opik, W&B Weave.

- 설정은 workspaces.settings["tracing"]에 둔다(마이그레이션 없음).
  {"include_content": bool, "providers": [{id, kind, name, enabled, sample_rate, only_failed,
   fields, secrets_enc, last}]}. 비밀값은 Fernet으로 암호화하고 화면·응답에는 ****abcd로만 보인다.
  v0.6 때 저장한 {"langfuse": {...}, "langsmith": {...}} 모양도 그대로 읽고, 다음 저장 때 목록으로 옮긴다.
- 서비스마다 켜고 끄기, 표본 비율(0~100%), '실패한 실행만 보내기', 마지막 전송 결과를 따로 가진다.
- 개인정보: 기본은 '내용 빼고' 보낸다(메타데이터·토큰·단계 이름). 입력·결과 내용은 워크스페이스가
  "입력·출력 내용 포함"을 켰을 때만, 비밀 환경 값을 가리고 2KB로 잘라서 보낸다.
- 실행이 끝나면(`_after_finish`) 보낼 곳이 있을 때만 큐(워커)에 올리고, 테스트(GENIO_RUN_INLINE)면 바로 보낸다.
  전송 실패는 기록만 남기고 실행 결과에는 영향이 없다. 외부 호출은 safe_http(사설 IP 차단)를 거친다.
"""

import base64
import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from api.config import get_settings
from api.core.crypto import decrypt_str, encrypt_str, mask, redact
from api.core.errors import AppError
from api.engine import safe_http
from api.models import App, Run, Workspace
from api.services import trace_model as tm
from nodes import NodeError

log = logging.getLogger("genio.tracing")

SEND_TRACE = "genio.send_trace"
MAX_PROVIDERS = 10
MAX_HEADERS = 8
LANGFUSE_DEFAULT_HOST = "https://cloud.langfuse.com"
LANGSMITH_DEFAULT_ENDPOINT = "https://api.smith.langchain.com"
_HEADER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _f(
    key: str,
    label: str,
    type_: str = "text",
    *,
    required: bool = False,
    default: str = "",
    hint: str = "",
    placeholder: str = "",
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "type": type_,
        "required": required,
        "default": default,
        "hint": hint,
        "placeholder": placeholder,
    }


# 서비스 종류와 입력 칸(화면은 이 목록으로 폼을 그린다). type: text | url | secret | headers
KINDS: dict[str, dict[str, Any]] = {
    "langfuse": {
        "label": "Langfuse",
        "experimental": False,
        "description": "클라우드 또는 직접 설치한 Langfuse. 단계별 기록과 AI 사용량을 봐요.",
        "fields": [
            _f(
                "host",
                "주소",
                "url",
                default=LANGFUSE_DEFAULT_HOST,
                hint="예: https://cloud.langfuse.com",
            ),
            _f("public_key", "공개 키(pk-lf-…)", required=True),
            _f("secret_key", "비밀 키(sk-lf-…)", "secret", required=True),
        ],
    },
    "langsmith": {
        "label": "LangSmith",
        "experimental": False,
        "description": "LangChain의 추적 서비스.",
        "fields": [
            _f("endpoint", "주소", "url", default=LANGSMITH_DEFAULT_ENDPOINT),
            _f("project", "프로젝트 이름", default="genio"),
            _f("api_key", "API 키", "secret", required=True),
        ],
    },
    "otlp": {
        "label": "OpenTelemetry(OTLP)",
        "experimental": False,
        "description": "OpenTelemetry 수집기(Collector)나 Jaeger·Grafana Tempo·Datadog 등 OTLP/HTTP를 받는 곳.",
        "fields": [
            _f(
                "endpoint",
                "수집기 주소",
                "url",
                required=True,
                placeholder="https://collector.example.com:4318",
                hint="뒤에 /v1/traces를 붙여 보내요. 이미 붙어 있으면 그대로 써요.",
            ),
            _f("service_name", "서비스 이름", default="genio"),
            _f(
                "headers",
                "추가 헤더",
                "headers",
                hint="인증이 필요하면 Authorization 같은 헤더를 넣으세요. 값은 암호화해 저장해요.",
            ),
        ],
    },
    "phoenix": {
        "label": "Arize Phoenix",
        "experimental": False,
        "description": "오픈소스 Phoenix(직접 설치) 또는 Phoenix Cloud. OTLP로 보내요.",
        "fields": [
            _f(
                "endpoint",
                "주소",
                "url",
                default="http://localhost:6006",
                hint="Phoenix 주소. 뒤에 /v1/traces를 붙여 보내요.",
            ),
            _f("project", "프로젝트 이름", default="genio"),
            _f("api_key", "API 키", "secret", hint="Phoenix Cloud나 인증을 켠 서버만 필요해요."),
        ],
    },
    "arize": {
        "label": "Arize AX",
        "experimental": True,
        "description": "Arize AX(클라우드). 헤더 이름이 문서마다 달라 두 가지를 함께 보내요.",
        "fields": [
            _f(
                "endpoint",
                "주소",
                "url",
                default="https://otlp.arize.com",
                hint="지역별 주소가 다르면 바꾸세요.",
            ),
            _f("space_id", "스페이스 ID", required=True),
            _f("project", "프로젝트(모델) 이름", default="genio"),
            _f("api_key", "API 키", "secret", required=True),
        ],
    },
    "opik": {
        "label": "Opik(Comet)",
        "experimental": True,
        "description": "Comet의 Opik. 클라우드는 기본 주소를 쓰고, 직접 설치했다면 그 주소를 넣어요.",
        "fields": [
            _f("host", "주소", "url", default="https://www.comet.com/opik/api"),
            _f("workspace", "워크스페이스 이름", required=True),
            _f("project", "프로젝트 이름", default="genio"),
            _f("api_key", "API 키", "secret", required=True),
        ],
    },
    "weave": {
        "label": "W&B Weave",
        "experimental": True,
        "description": "Weights & Biases의 Weave 추적.",
        "fields": [
            _f("host", "주소", "url", default="https://trace.wandb.ai"),
            _f("entity", "엔티티(팀·사용자 이름)", required=True),
            _f("project", "프로젝트 이름", required=True),
            _f("api_key", "API 키", "secret", required=True),
        ],
    },
}


def kinds_public() -> list[dict[str, Any]]:
    return [{"kind": k, **v} for k, v in KINDS.items()]


# ---------------- 설정 읽기·쓰기 ----------------
def _cfg(ws: Workspace) -> dict[str, Any]:
    cfg = (ws.settings or {}).get("tracing")
    return dict(cfg) if isinstance(cfg, dict) else {}


def _dec(value: Any) -> str:
    if not value:
        return ""
    try:
        return decrypt_str(str(value).encode())
    except ValueError:
        return ""


def _enc(value: str) -> str:
    return encrypt_str(value).decode()


def _specs(kind: str) -> list[dict[str, Any]]:
    return list(KINDS[kind]["fields"])


def _legacy_providers(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """v0.6 모양({"langfuse": {...}, "langsmith": {...}})을 목록 항목으로 바꾼다(저장은 하지 않는다)."""
    out: list[dict[str, Any]] = []
    lf = cfg.get("langfuse")
    if isinstance(lf, dict):
        enc: dict[str, str] = {}
        if lf.get("secret_key_enc"):
            enc["secret_key"] = str(lf["secret_key_enc"])
        out.append(
            {
                "id": "langfuse",
                "kind": "langfuse",
                "name": "Langfuse",
                "enabled": bool(lf.get("enabled")),
                "sample_rate": 100,
                "only_failed": False,
                "fields": {
                    "host": str(lf.get("host") or LANGFUSE_DEFAULT_HOST),
                    "public_key": str(lf.get("public_key") or ""),
                },
                "secrets_enc": enc,
            }
        )
    ls = cfg.get("langsmith")
    if isinstance(ls, dict):
        enc = {}
        if ls.get("api_key_enc"):
            enc["api_key"] = str(ls["api_key_enc"])
        out.append(
            {
                "id": "langsmith",
                "kind": "langsmith",
                "name": "LangSmith",
                "enabled": bool(ls.get("enabled")),
                "sample_rate": 100,
                "only_failed": False,
                "fields": {
                    "endpoint": str(ls.get("endpoint") or LANGSMITH_DEFAULT_ENDPOINT),
                    "project": str(ls.get("project") or "genio"),
                },
                "secrets_enc": enc,
            }
        )
    return out


def providers_of(ws: Workspace) -> list[dict[str, Any]]:
    cfg = _cfg(ws)
    raw = cfg.get("providers")
    items = (
        [dict(p) for p in raw if isinstance(p, dict) and p.get("kind") in KINDS]
        if isinstance(raw, list)
        else _legacy_providers(cfg)
    )
    return items


def _field_value(p: dict[str, Any], spec: dict[str, Any]) -> str:
    v = str((p.get("fields") or {}).get(spec["key"]) or "").strip()
    return v or str(spec["default"])


def _header_names(p: dict[str, Any]) -> list[str]:
    names = (p.get("fields") or {}).get("headers")
    return [str(n) for n in names] if isinstance(names, list) else []


def is_ready(p: dict[str, Any]) -> bool:
    """필수 칸이 모두 채워졌나(켜져 있어도 비어 있으면 보내지 않는다)."""
    for spec in _specs(p["kind"]):
        if not spec["required"]:
            continue
        if spec["type"] == "secret":
            if not _dec((p.get("secrets_enc") or {}).get(spec["key"])):
                return False
        elif spec["type"] != "headers" and not _field_value(p, spec):
            return False
    return True


def public_provider(p: dict[str, Any]) -> dict[str, Any]:
    kind = p["kind"]
    fields: dict[str, Any] = {}
    secrets: dict[str, Any] = {}
    headers: list[dict[str, Any]] = []
    for spec in _specs(kind):
        key = spec["key"]
        if spec["type"] == "secret":
            plain = _dec((p.get("secrets_enc") or {}).get(key))
            secrets[key] = {"has": bool(plain), "masked": mask(plain) if plain else ""}
        elif spec["type"] == "headers":
            for name in _header_names(p):
                plain = _dec((p.get("secrets_enc") or {}).get(f"h:{name}"))
                headers.append({"name": name, "masked": mask(plain) if plain else ""})
        else:
            fields[key] = _field_value(p, spec)
    last = p.get("last") if isinstance(p.get("last"), dict) else None
    return {
        "id": p["id"],
        "kind": kind,
        "kind_label": KINDS[kind]["label"],
        "experimental": bool(KINDS[kind]["experimental"]),
        "name": str(p.get("name") or KINDS[kind]["label"]),
        "enabled": bool(p.get("enabled")),
        "sample_rate": int(p.get("sample_rate", 100)),
        "only_failed": bool(p.get("only_failed")),
        "fields": fields,
        "secrets": secrets,
        "headers": headers,
        "ready": is_ready(p),
        "last": last,
    }


def _legacy_public(providers: list[dict[str, Any]]) -> dict[str, Any]:
    """v0.6 화면·시험이 읽던 모양(첫 Langfuse·LangSmith 항목)."""
    lf = next((p for p in providers if p["kind"] == "langfuse"), None)
    ls = next((p for p in providers if p["kind"] == "langsmith"), None)
    lf_pub = public_provider(lf) if lf else None
    ls_pub = public_provider(ls) if ls else None
    return {
        "langfuse": {
            "enabled": bool(lf and lf.get("enabled")),
            "host": lf_pub["fields"]["host"] if lf_pub else LANGFUSE_DEFAULT_HOST,
            "public_key": lf_pub["fields"]["public_key"] if lf_pub else "",
            "secret_key": lf_pub["secrets"]["secret_key"]["masked"] if lf_pub else "",
            "has_secret": bool(lf_pub and lf_pub["secrets"]["secret_key"]["has"]),
        },
        "langsmith": {
            "enabled": bool(ls and ls.get("enabled")),
            "endpoint": ls_pub["fields"]["endpoint"] if ls_pub else LANGSMITH_DEFAULT_ENDPOINT,
            "project": ls_pub["fields"]["project"] if ls_pub else "genio",
            "api_key": ls_pub["secrets"]["api_key"]["masked"] if ls_pub else "",
            "has_key": bool(ls_pub and ls_pub["secrets"]["api_key"]["has"]),
        },
    }


def public_config(ws: Workspace) -> dict[str, Any]:
    """화면용 설정: 비밀값은 ****abcd로만."""
    providers = providers_of(ws)
    return {
        "include_content": bool(_cfg(ws).get("include_content")),
        "kinds": kinds_public(),
        "providers": [public_provider(p) for p in providers],
        **_legacy_public(providers),
    }


def _clean_url(value: Any, default: str) -> str:
    url = str(value or "").strip().rstrip("/") or default
    if not url.startswith(("http://", "https://")):
        raise AppError(
            422,
            "주소는 http:// 또는 https://로 시작해야 해요.",
            "예: https://cloud.langfuse.com 처럼 전체 주소를 넣어 주세요.",
        )
    return url[:300]


def _clamp_rate(value: Any, default: int = 100) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return default


def _new_id(taken: set[str]) -> str:
    while True:
        pid = uuid.uuid4().hex[:8]
        if pid not in taken:
            return pid


def _merge_provider(
    existing: dict[str, Any] | None, item: dict[str, Any], taken: set[str]
) -> dict[str, Any]:
    kind = str(existing["kind"] if existing else item.get("kind") or "")
    if kind not in KINDS:
        raise AppError(422, "알 수 없는 추적 서비스예요.", "추가 메뉴에서 서비스를 골라 주세요.")
    p: dict[str, Any] = (
        dict(existing) if existing else {"kind": kind, "fields": {}, "secrets_enc": {}}
    )
    p["id"] = existing["id"] if existing else _new_id(taken)
    p["name"] = str(item.get("name") or p.get("name") or KINDS[kind]["label"]).strip()[:60]
    p["enabled"] = bool(item.get("enabled", p.get("enabled", False)))
    p["sample_rate"] = _clamp_rate(item.get("sample_rate", p.get("sample_rate", 100)))
    p["only_failed"] = bool(item.get("only_failed", p.get("only_failed", False)))
    raw_fields = item.get("fields")
    incoming: dict[str, Any] = raw_fields if isinstance(raw_fields, dict) else {}
    raw_secrets = item.get("secrets")
    secrets_in: dict[str, Any] = raw_secrets if isinstance(raw_secrets, dict) else {}
    clear = {str(k) for k in (item.get("clear_secrets") or [])}
    fields: dict[str, Any] = dict(p.get("fields") or {})
    enc: dict[str, str] = dict(p.get("secrets_enc") or {})
    for spec in _specs(kind):
        key = spec["key"]
        if spec["type"] == "secret":
            raw = str(secrets_in.get(key) or "").strip()
            if raw and not raw.startswith("****"):
                enc[key] = _enc(raw[:500])
            if key in clear:
                enc.pop(key, None)
        elif spec["type"] == "headers":
            names: list[str] = []
            old_enc = {k: v for k, v in enc.items() if k.startswith("h:")}
            for k in old_enc:
                enc.pop(k, None)
            raw_headers = item.get("headers")
            entries: list[Any] = raw_headers if isinstance(raw_headers, list) else []
            for entry in entries[:MAX_HEADERS]:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("name") or "").strip()
                if not name:
                    continue
                if not _HEADER_NAME.match(name):
                    raise AppError(
                        422,
                        f"헤더 이름 '{name[:20]}'을(를) 쓸 수 없어요.",
                        "영문·숫자·밑줄·하이픈만 쓰고 64자 안으로 적어 주세요.",
                    )
                value = str(entry.get("value") or "").strip()
                if "\n" in value or "\r" in value:
                    raise AppError(422, "헤더 값에 줄바꿈이 있어요.", "한 줄로 적어 주세요.")
                if value and not value.startswith("****"):
                    enc[f"h:{name}"] = _enc(value[:500])
                elif f"h:{name}" in old_enc:
                    enc[f"h:{name}"] = old_enc[f"h:{name}"]
                if name not in names:
                    names.append(name)
            fields["headers"] = names
        elif spec["type"] == "url":
            raw_url = incoming.get(key, fields.get(key))
            fields[key] = (
                _clean_url(raw_url, str(spec["default"])) if (raw_url or spec["default"]) else ""
            )
        else:
            value = str(incoming.get(key, fields.get(key)) or "").strip()
            fields[key] = value[:200]
    p["fields"] = fields
    p["secrets_enc"] = enc
    return p


def _apply_legacy(providers: list[dict[str, Any]], kind: str, body: dict[str, Any]) -> None:
    """v0.6 모양 입력({"langfuse": {...}} 등)을 목록 항목에 반영한다."""
    existing = next((p for p in providers if p["kind"] == kind), None)
    if kind == "langfuse":
        item: dict[str, Any] = {
            "enabled": body.get("enabled"),
            "fields": {"host": body.get("host"), "public_key": body.get("public_key")},
            "secrets": {"secret_key": body.get("secret_key")},
            "clear_secrets": ["secret_key"] if body.get("clear_secret") else [],
        }
    else:
        item = {
            "enabled": body.get("enabled"),
            "fields": {"endpoint": body.get("endpoint"), "project": body.get("project")},
            "secrets": {"api_key": body.get("api_key")},
            "clear_secrets": ["api_key"] if body.get("clear_key") else [],
        }
    item["enabled"] = bool(item["enabled"])
    taken = {p["id"] for p in providers}
    if existing is None:
        item["kind"] = kind
        merged = _merge_provider(None, item, taken)
        merged["id"] = kind if kind not in taken else merged["id"]
        providers.append(merged)
        return
    providers[providers.index(existing)] = _merge_provider(existing, item, taken)


def save_config(ws: Workspace, body: dict[str, Any]) -> dict[str, Any]:
    """설정을 저장한다. 비밀값 칸이 비어 있거나 ****로 시작하면 저장된 값을 그대로 둔다."""
    cfg = _cfg(ws)
    providers = providers_of(ws)  # 예전 모양이면 여기서 목록으로 옮겨 진다
    if "include_content" in body:
        cfg["include_content"] = bool(body["include_content"])
    items = body.get("providers")
    if isinstance(items, list):
        if len(items) > MAX_PROVIDERS:
            raise AppError(
                422,
                f"추적 서비스는 {MAX_PROVIDERS}개까지 연결할 수 있어요.",
                "안 쓰는 서비스를 지운 뒤 다시 저장하세요.",
            )
        by_id = {p["id"]: p for p in providers}
        merged: list[dict[str, Any]] = []
        taken: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            existing = by_id.get(str(item.get("id") or ""))
            if existing is not None and existing["id"] in taken:
                existing = None
            p = _merge_provider(existing, item, taken)
            taken.add(p["id"])
            merged.append(p)
        providers = merged
    else:
        for kind in ("langfuse", "langsmith"):
            legacy = body.get(kind)
            if isinstance(legacy, dict):
                _apply_legacy(providers, kind, legacy)
    cfg["providers"] = providers
    cfg.pop("langfuse", None)
    cfg.pop("langsmith", None)
    ws.settings = {**(ws.settings or {}), "tracing": cfg}
    return public_config(ws)


def enabled(ws: Workspace | None) -> bool:
    return ws is not None and any(p.get("enabled") for p in providers_of(ws))


# ---------------- 보낼지 정하기 ----------------
def sampled(run_id: str, rate: int) -> bool:
    """실행마다 같은 답이 나오는 표본 추출(재시도해도 같은 실행은 같은 결정)."""
    if rate >= 100:
        return True
    if rate <= 0:
        return False
    return int(hashlib.sha256(run_id.encode()).hexdigest()[:8], 16) % 100 < rate


def wanted(ws: Workspace, run: Run) -> list[dict[str, Any]]:
    """이 실행을 받을 서비스(켜짐·필수 칸 있음·표본·실패만 조건을 모두 통과한 곳)."""
    out = []
    for p in providers_of(ws):
        if not p.get("enabled") or not is_ready(p):
            continue
        if p.get("only_failed") and run.status != "failed":
            continue
        if not sampled(run.id, int(p.get("sample_rate", 100))):
            continue
        out.append(p)
    return out


# ---------------- 서비스별 보내기 ----------------
def _resolved(p: dict[str, Any]) -> dict[str, Any]:
    """보내기 직전에만 쓰는 값(비밀값이 풀린 상태, 밖으로 내보내지 않는다)."""
    kind = p["kind"]
    values: dict[str, Any] = {}
    for spec in _specs(kind):
        if spec["type"] == "secret":
            values[spec["key"]] = _dec((p.get("secrets_enc") or {}).get(spec["key"]))
        elif spec["type"] == "headers":
            values["headers"] = {
                n: _dec((p.get("secrets_enc") or {}).get(f"h:{n}")) for n in _header_names(p)
            }
        else:
            values[spec["key"]] = _field_value(p, spec)
    return values


def _secrets_in(values: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for v in values.values():
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            out.extend(str(x) for x in v.values())
    return [s for s in out if s]


def _http_error(name: str, status: int) -> str | None:
    if status in (401, 403):
        return f"{name}가 키를 받아 주지 않았어요(인증 실패). 키와 주소를 확인하세요."
    if status >= 400:
        return f"{name}가 요청을 받지 않았어요(응답 {status})."
    return None


def _call(
    name: str,
    method: str,
    url: str,
    headers: dict[str, str],
    body: Any,
    secrets: list[str],
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        res = safe_http.request(method, url, headers=headers, body=body)
    except NodeError as exc:
        return None, redact(exc.message, secrets)
    return res, _http_error(name, int(res.get("status") or 0))


def _send_langfuse(v: dict[str, Any], rec: tm.TraceRec) -> str | None:
    token = base64.b64encode(f"{v['public_key']}:{v['secret_key']}".encode()).decode()
    res, err = _call(
        "Langfuse",
        "POST",
        f"{str(v['host']).rstrip('/')}/api/public/ingestion",
        {"Authorization": f"Basic {token}", "Content-Type": "application/json"},
        {"batch": tm.build_langfuse(rec)},
        _secrets_in(v),
    )
    if err or res is None:
        return err
    body = res.get("body")
    errors = body.get("errors") if isinstance(body, dict) else None
    if errors:
        return f"Langfuse가 일부 기록을 받지 않았어요({len(errors)}건)."
    return None


def _send_langsmith(v: dict[str, Any], rec: tm.TraceRec) -> str | None:
    _, err = _call(
        "LangSmith",
        "POST",
        f"{str(v['endpoint']).rstrip('/')}/runs/batch",
        {"x-api-key": str(v["api_key"]), "Content-Type": "application/json"},
        {"post": tm.build_langsmith(rec, str(v["project"]))},
        _secrets_in(v),
    )
    return err


def _traces_url(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    return base if base.endswith("/v1/traces") else f"{base}/v1/traces"


def _send_otlp_like(
    name: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    secrets: list[str],
) -> str | None:
    res, err = _call(
        name, "POST", url, {"Content-Type": "application/json", **headers}, payload, secrets
    )
    if err or res is None:
        return err
    body = res.get("body")
    partial = body.get("partialSuccess") if isinstance(body, dict) else None
    rejected = int(partial.get("rejectedSpans") or 0) if isinstance(partial, dict) else 0
    if rejected:
        return f"{name}가 일부 기록을 받지 않았어요({rejected}건)."
    return None


def _send_otlp(v: dict[str, Any], rec: tm.TraceRec) -> str | None:
    headers = {n: val for n, val in dict(v.get("headers") or {}).items() if val}
    payload = tm.build_otlp(rec, service_name=str(v["service_name"]))
    return _send_otlp_like(
        "OpenTelemetry 수집기", _traces_url(str(v["endpoint"])), headers, payload, _secrets_in(v)
    )


def _send_phoenix(v: dict[str, Any], rec: tm.TraceRec) -> str | None:
    project = str(v["project"])
    headers = {"x-project-name": project}
    if v.get("api_key"):
        headers["Authorization"] = f"Bearer {v['api_key']}"
    payload = tm.build_otlp(
        rec,
        service_name=project,
        resource={"openinference.project.name": project},
        openinference=True,
    )
    return _send_otlp_like(
        "Phoenix", _traces_url(str(v["endpoint"])), headers, payload, _secrets_in(v)
    )


def _send_arize(v: dict[str, Any], rec: tm.TraceRec) -> str | None:
    project = str(v["project"])
    # OTLP/HTTP는 하이픈, gRPC는 밑줄 이름을 문서가 안내해서 두 가지를 함께 보낸다
    headers = {
        "arize-space-id": str(v["space_id"]),
        "arize-api-key": str(v["api_key"]),
        "space_id": str(v["space_id"]),
        "api_key": str(v["api_key"]),
    }
    payload = tm.build_otlp(
        rec,
        service_name=project,
        resource={
            "model_id": project,
            "model_version": "1",
            "openinference.project.name": project,
        },
        openinference=True,
    )
    return _send_otlp_like(
        "Arize AX", _traces_url(str(v["endpoint"])), headers, payload, _secrets_in(v)
    )


def _send_opik(v: dict[str, Any], rec: tm.TraceRec) -> str | None:
    base = str(v["host"]).rstrip("/")
    headers = {
        "Authorization": str(v["api_key"]),
        "Comet-Workspace": str(v["workspace"]),
        "Content-Type": "application/json",
    }
    traces, spans = tm.build_opik(rec, str(v["project"]))
    secrets = _secrets_in(v)
    _, err = _call(
        "Opik", "POST", f"{base}/v1/private/traces/batch", headers, {"traces": traces}, secrets
    )
    if err:
        return err
    if spans:
        _, err = _call(
            "Opik", "POST", f"{base}/v1/private/spans/batch", headers, {"spans": spans}, secrets
        )
    return err


def _send_weave(v: dict[str, Any], rec: tm.TraceRec) -> str | None:
    token = base64.b64encode(f"api:{v['api_key']}".encode()).decode()
    project_id = f"{v['entity']}/{v['project']}"
    _, err = _call(
        "Weave",
        "POST",
        f"{str(v['host']).rstrip('/')}/call/upsert_batch",
        {"Authorization": f"Basic {token}", "Content-Type": "application/json"},
        {"batch": tm.build_weave(rec, project_id)},
        _secrets_in(v),
    )
    return err


SENDERS = {
    "langfuse": _send_langfuse,
    "langsmith": _send_langsmith,
    "otlp": _send_otlp,
    "phoenix": _send_phoenix,
    "arize": _send_arize,
    "opik": _send_opik,
    "weave": _send_weave,
}


def _send_one(p: dict[str, Any], rec: tm.TraceRec) -> str | None:
    return SENDERS[p["kind"]](_resolved(p), rec)


def _record_last(
    db: Session, ws: Workspace, results: dict[str, str | None], note: str = ""
) -> None:
    """서비스마다 마지막 전송 결과(시각·성공 여부·문장)를 설정에 남긴다(비밀값 없음)."""
    cfg = _cfg(ws)
    items = providers_of(ws)
    if not items or not results:
        return
    now = datetime.now(UTC).isoformat()
    for p in items:
        if p["id"] in results:
            err = results[p["id"]]
            p["last"] = {
                "at": now,
                "ok": err is None,
                "message": (note or "보냈어요.") if err is None else str(err)[:300],
            }
    cfg["providers"] = items
    cfg.pop("langfuse", None)
    cfg.pop("langsmith", None)
    ws.settings = {**(ws.settings or {}), "tracing": cfg}
    db.commit()


def send_run(db: Session, run_id: str) -> dict[str, str | None]:
    """실행 하나를 받을 서비스에 보낸다. {서비스 id: 실패 문장 | None}."""
    run = db.get(Run, run_id)
    if run is None:
        return {}
    app = db.get(App, run.app_id)
    ws = db.get(Workspace, app.workspace_id) if app else None
    if app is None or ws is None:
        return {}
    targets = wanted(ws, run)
    if not targets:
        return {}
    include = bool(_cfg(ws).get("include_content"))
    rec = tm.collect(db, run, app, include)
    results: dict[str, str | None] = {}
    for p in targets:
        try:
            results[p["id"]] = _send_one(p, rec)
        except Exception as exc:  # 추적은 실행에 영향을 주지 않는다
            log.warning(
                "외부 추적 전송 오류(run=%s, %s): %s", run_id, p["kind"], type(exc).__name__
            )
            results[p["id"]] = "보내는 중 문제가 생겼어요."
        if results[p["id"]]:
            log.warning("외부 추적 전송 실패(run=%s, %s): %s", run_id, p["kind"], results[p["id"]])
    try:
        _record_last(db, ws, results)
    except Exception:
        db.rollback()
        log.warning("외부 추적 결과 기록 실패(run=%s)", run_id)
    return results


def dispatch_trace(db: Session, run: Run) -> None:
    """끝난 실행을 보낼 차례에 올린다(받을 서비스가 있는 워크스페이스만)."""
    app = db.get(App, run.app_id)
    ws = db.get(Workspace, app.workspace_id) if app else None
    if ws is None or not enabled(ws) or not wanted(ws, run):
        return
    if get_settings().genio_run_inline:
        send_run(db, run.id)
        return
    from api.services.queue import _client

    _client().send_task(SEND_TRACE, args=[run.id])


# ---------------- 연결 시험 ----------------
_MISSING = {
    "langfuse": "공개 키와 비밀 키를 먼저 저장해 주세요.",
    "langsmith": "API 키를 먼저 저장해 주세요.",
}


def test_connection(db: Session, ws: Workspace, target: str) -> dict[str, Any]:
    """작은 시험 기록을 하나 보내 본다. 켜져 있지 않아도 필수 칸이 있으면 시험한다."""
    p = next((x for x in providers_of(ws) if x["id"] == target), None)
    if p is None and target in _MISSING:
        return {"ok": False, "message": _MISSING[target]}
    if p is None:
        return {"ok": False, "message": "알 수 없는 추적 서비스예요. 목록에서 다시 골라 주세요."}
    if not is_ready(p):
        return {
            "ok": False,
            "message": _MISSING.get(p["kind"], "필수 칸(키·주소 등)을 먼저 채우고 저장해 주세요."),
        }
    try:
        err = _send_one(p, tm.test_record())
    except Exception as exc:
        log.warning("외부 추적 연결 시험 오류(%s): %s", p["kind"], type(exc).__name__)
        err = "보내는 중 문제가 생겼어요."
    try:
        _record_last(db, ws, {p["id"]: err}, note="연결 시험을 보냈어요.")
    except Exception:
        db.rollback()
    if err is None:
        return {
            "ok": True,
            "message": "시험 기록을 보냈어요. 상대 화면에서 'Genio 연결 시험'을 확인하세요.",
        }
    return {"ok": False, "message": err}
