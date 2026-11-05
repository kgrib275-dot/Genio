"""서비스 이벤트로 시작하기(v0.9, ADR 0013): Slack·GitHub·Shopify·Telegram·Jira·Typeform.

외부 서비스가 보내는 알림(웹훅)을 서비스마다 다른 서명 방식으로 확인하고, 이벤트 이름·보낸 번호를 읽어
걸러 내고(이벤트 칩, 봇 메시지), 같은 알림이 다시 오면 무시하고(10분), 받은 값 중 필요한 것을 흐름의
입력 칸에 옮겨(값 연결) 실행을 만든다. 서명 비밀값은 암호화해 저장하고 로그·오류에 남기지 않는다.
"""

import base64
import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import redis

from api.core.errors import AppError
from api.engine.events import _client

SLACK_TOLERANCE_SECONDS = 300
DEDUPE_SECONDS = 600
MAX_MAPPING = 30
MAX_PATH = 200
MAX_VALUE_CHARS = 8000


# ---------------- 서비스 목록(화면에도 그대로 보여 준다) ----------------
@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    # generated: 제니오가 만들어 한 번 보여 주는 값을 서비스에 붙여 넣는다
    # provider: 서비스가 정해 준 값(Slack 서명 비밀값, Shopify 앱 비밀 키)을 제니오에 붙여 넣는다
    key_origin: str
    key_label: str
    events: tuple[tuple[str, str], ...]
    instructions: tuple[str, ...]
    sample_headers: dict[str, str] = field(default_factory=dict)
    sample_body: dict[str, Any] = field(default_factory=dict)


PRESETS: dict[str, Preset] = {
    "slack": Preset(
        key="slack",
        name="Slack",
        key_origin="provider",
        key_label="Slack 앱의 Signing Secret(서명 비밀값)",
        events=(
            ("message", "채널 메시지"),
            ("app_mention", "앱을 부름(@멘션)"),
            ("reaction_added", "이모지 반응"),
        ),
        instructions=(
            "api.slack.com/apps에서 앱을 만들고 Basic Information의 Signing Secret을 복사해 아래 칸에 붙여 넣어요.",
            "Event Subscriptions를 켜고 Request URL에 아래 주소를 붙여 넣으면 Slack이 확인 요청을 보내고, 제니오가 알아서 답해요.",
            "Subscribe to bot events에서 받을 이벤트(message.channels, app_mention, reaction_added 등)를 추가하고 앱을 채널에 초대하세요.",
        ),
        sample_headers={},
        sample_body={
            "type": "event_callback",
            "event_id": "Ev0SAMPLE",
            "team_id": "T0SAMPLE",
            "event": {
                "type": "message",
                "user": "U0SAMPLE",
                "channel": "C0SAMPLE",
                "text": "배송이 늦어지고 있어요. 확인해 주세요.",
                "ts": "1730000000.000100",
            },
        },
    ),
    "github": Preset(
        key="github",
        name="GitHub",
        key_origin="generated",
        key_label="웹훅 Secret",
        events=(
            ("issues:opened", "이슈 만듦"),
            ("issues:closed", "이슈 닫힘"),
            ("pull_request:opened", "PR 만듦"),
            ("pull_request:closed", "PR 닫힘/머지"),
            ("issue_comment:created", "댓글 달림"),
            ("push", "푸시"),
            ("release:published", "릴리스 공개"),
        ),
        instructions=(
            "저장소(또는 조직) Settings > Webhooks > Add webhook을 열어요.",
            "Payload URL에 아래 주소를, Content type은 application/json, Secret에 아래 비밀값을 붙여 넣어요.",
            "'Let me select individual events'에서 받을 이벤트를 고르고 저장하세요.",
        ),
        sample_headers={"x-github-event": "issues"},
        sample_body={
            "action": "opened",
            "issue": {
                "number": 42,
                "title": "로그인 화면이 열리지 않아요",
                "body": "크롬에서 로그인 버튼을 눌러도 반응이 없어요.",
                "html_url": "https://github.com/acme/app/issues/42",
                "user": {"login": "hong"},
            },
            "repository": {"full_name": "acme/app"},
            "sender": {"login": "hong"},
        },
    ),
    "shopify": Preset(
        key="shopify",
        name="Shopify",
        key_origin="provider",
        key_label="Shopify 앱의 API secret key(클라이언트 시크릿)",
        events=(
            ("orders/create", "주문 생성"),
            ("orders/paid", "결제 완료"),
            ("orders/cancelled", "주문 취소"),
            ("customers/create", "고객 가입"),
            ("refunds/create", "환불"),
        ),
        instructions=(
            "Shopify 관리자 > 설정 > 알림(Notifications) > 웹훅, 또는 앱의 웹훅 설정을 열어요.",
            "이벤트(예: 주문 생성)를 고르고 형식은 JSON, URL에 아래 주소를 붙여 넣어요.",
            "서명에 쓰이는 'API secret key'(앱 설정에서 확인)를 아래 칸에 붙여 넣어요.",
        ),
        sample_headers={"x-shopify-topic": "orders/create"},
        sample_body={
            "id": 820982911946154508,
            "name": "#1001",
            "total_price": "118000.00",
            "currency": "KRW",
            "email": "customer@example.com",
            "line_items": [{"title": "웹캠", "quantity": 2, "price": "59000.00"}],
        },
    ),
    "telegram": Preset(
        key="telegram",
        name="Telegram",
        key_origin="generated",
        key_label="secret_token",
        events=(("message", "메시지"),),
        instructions=(
            "@BotFather로 봇을 만들고 토큰을 받아요.",
            "브라우저에서 https://api.telegram.org/bot<봇 토큰>/setWebhook?url=<아래 주소>&secret_token=<아래 비밀값> 을 열어요.",
            "봇에게 메시지를 보내면 흐름이 시작돼요. 받은 chat id로 답장하는 단계를 이어 붙이세요.",
        ),
        sample_headers={},
        sample_body={
            "update_id": 100001,
            "message": {
                "message_id": 7,
                "from": {"id": 111, "first_name": "길동", "username": "hong"},
                "chat": {"id": 111, "type": "private"},
                "text": "내일 회의실 예약해 줘",
            },
        },
    ),
    "jira": Preset(
        key="jira",
        name="Jira",
        key_origin="generated",
        key_label="공유 비밀값",
        events=(
            ("jira:issue_created", "이슈 만듦"),
            ("jira:issue_updated", "이슈 고침"),
            ("comment_created", "댓글 달림"),
        ),
        instructions=(
            "Jira 설정 > 시스템 > 웹훅(WebHooks) > 웹훅 만들기를 열어요.",
            "URL에 아래 주소 뒤에 ?secret=아래 비밀값 을 붙여 넣고, 받을 이벤트를 골라요. (Jira가 서명(X-Hub-Signature)을 지원하면 비밀값으로 서명도 확인해요.)",
            "비밀값이 맞지 않는 요청은 거절돼요.",
        ),
        sample_headers={},
        sample_body={
            "webhookEvent": "jira:issue_created",
            "timestamp": 1730000000000,
            "issue": {
                "key": "OPS-17",
                "fields": {
                    "summary": "결제 오류 문의",
                    "description": "카드 결제가 두 번 됐어요.",
                    "reporter": {"displayName": "김고객"},
                    "priority": {"name": "High"},
                },
            },
        },
    ),
    "typeform": Preset(
        key="typeform",
        name="Typeform",
        key_origin="generated",
        key_label="Secret",
        events=(("form_response", "설문 응답 도착"),),
        instructions=(
            "Typeform 설문 > Connect > Webhooks > Add a webhook을 열어요.",
            "Destination URL에 아래 주소를, Secret에 아래 비밀값을 붙여 넣고 켜세요.",
            "응답이 올 때마다 흐름이 시작돼요. 질문별 답은 '값 연결'에서 골라 입력 칸에 넣어요.",
        ),
        sample_headers={},
        sample_body={
            "event_id": "01SAMPLE",
            "event_type": "form_response",
            "form_response": {
                "form_id": "abc123",
                "definition": {"title": "고객 만족도 설문"},
                "answers": [
                    {"field": {"ref": "name"}, "type": "text", "text": "홍길동"},
                    {"field": {"ref": "score"}, "type": "number", "number": 9},
                ],
            },
        },
    ),
}


def preset_dict(p: Preset) -> dict[str, Any]:
    return {
        "key": p.key,
        "name": p.name,
        "key_origin": p.key_origin,
        "key_label": p.key_label,
        "events": [{"id": i, "label": label} for i, label in p.events],
        "instructions": list(p.instructions),
        "sample": {"headers": p.sample_headers, "body": p.sample_body},
    }


def preset_of(key: Any) -> Preset:
    p = PRESETS.get(str(key or ""))
    if p is None:
        raise AppError(
            422,
            "알 수 없는 서비스예요.",
            "Slack·GitHub·Shopify·Telegram·Jira·Typeform 중에서 골라 주세요.",
        )
    return p


# ---------------- 설정 정리 ----------------
def clean_service(config: dict[str, Any]) -> dict[str, Any]:
    preset = preset_of(config.get("service"))
    allowed = {i for i, _ in preset.events}
    events_in = config.get("events") or []
    if not isinstance(events_in, list):
        raise AppError(422, "받을 이벤트는 목록이어야 해요.", "화면의 이벤트 칩을 골라 주세요.")
    events = [str(e) for e in events_in if str(e)]
    bad = [e for e in events if e not in allowed]
    if bad:
        raise AppError(
            422,
            f"{preset.name}에서 받을 수 없는 이벤트가 있어요: {', '.join(bad[:3])}",
            "화면의 이벤트 칩에서 고르세요.",
        )
    mapping_in = config.get("mapping") or {}
    if not isinstance(mapping_in, dict) or len(mapping_in) > MAX_MAPPING:
        raise AppError(
            422,
            "값 연결 설정이 올바르지 않아요.",
            f"'입력 칸 이름: 받은 값 위치' 형태로 {MAX_MAPPING}개 이하로 적어 주세요.",
        )
    mapping: dict[str, str] = {}
    for k, v in mapping_in.items():
        key, path = str(k).strip(), str(v or "").strip()
        if not key or key.startswith("__"):
            continue
        if len(path) > MAX_PATH:
            raise AppError(422, "받은 값 위치가 너무 길어요.", f"{MAX_PATH}자 안으로 줄여 주세요.")
        if path:
            mapping[key[:64]] = path
    out: dict[str, Any] = {
        "service": preset.key,
        "events": events,
        "mapping": mapping,
        "include_bot": bool(config.get("include_bot")),
    }
    if config.get("version") is not None:
        try:
            n = int(config["version"])
        except (TypeError, ValueError):
            raise AppError(
                422, "버전 번호는 숫자여야 해요.", "비우면 저장한 최신 버전으로 실행해요."
            ) from None
        if n < 1:
            raise AppError(
                422, "버전 번호는 1 이상이에요.", "비우면 저장한 최신 버전으로 실행해요."
            )
        out["version"] = n
    return out


# ---------------- 서명 확인 ----------------
def _hex_mac(secret: str, msg: bytes) -> str:
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def _b64_mac(secret: str, msg: bytes) -> str:
    return base64.b64encode(hmac.new(secret.encode(), msg, hashlib.sha256).digest()).decode()


def _eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def verify(
    service: str,
    secret: str,
    headers: dict[str, str],
    body: bytes,
    query: dict[str, str] | None = None,
    now: float | None = None,
) -> str | None:
    """서명이 맞으면 None, 틀리면 이유(사람이 읽는 문구). 비밀값·서명 값은 문구에 넣지 않는다."""
    h = {k.lower(): v for k, v in headers.items()}
    if service == "slack":
        ts, sig = h.get("x-slack-request-timestamp", ""), h.get("x-slack-signature", "")
        if not ts or not sig:
            return "Slack 서명 헤더(X-Slack-Signature)가 없어요"
        try:
            sent = float(ts)
        except ValueError:
            return "X-Slack-Request-Timestamp가 숫자(초)가 아니에요"
        current = time.time() if now is None else now
        if abs(current - sent) > SLACK_TOLERANCE_SECONDS:
            return "보낸 시각이 5분 넘게 차이 나요(다시 보내기 공격 방지)"
        expected = "v0=" + _hex_mac(secret, b"v0:" + ts.encode() + b":" + body)
        return None if _eq(expected, sig.strip()) else "서명이 맞지 않아요"
    if service == "github":
        sig = h.get("x-hub-signature-256", "")
        if not sig:
            return "GitHub 서명 헤더(X-Hub-Signature-256)가 없어요"
        expected = "sha256=" + _hex_mac(secret, body)
        return None if _eq(expected, sig.strip()) else "서명이 맞지 않아요"
    if service == "shopify":
        sig = h.get("x-shopify-hmac-sha256", "")
        if not sig:
            return "Shopify 서명 헤더(X-Shopify-Hmac-Sha256)가 없어요"
        return None if _eq(_b64_mac(secret, body), sig.strip()) else "서명이 맞지 않아요"
    if service == "telegram":
        tok = h.get("x-telegram-bot-api-secret-token", "")
        if not tok:
            return "Telegram 비밀 토큰 헤더가 없어요(setWebhook에 secret_token을 넣으세요)"
        return None if _eq(secret, tok.strip()) else "비밀 토큰이 맞지 않아요"
    if service == "typeform":
        sig = h.get("typeform-signature", "")
        if not sig:
            return "Typeform 서명 헤더(Typeform-Signature)가 없어요"
        return (
            None if _eq("sha256=" + _b64_mac(secret, body), sig.strip()) else "서명이 맞지 않아요"
        )
    if service == "jira":
        sig = h.get("x-hub-signature", "")
        if sig:
            return (
                None
                if _eq("sha256=" + _hex_mac(secret, body), sig.strip())
                else "서명이 맞지 않아요"
            )
        shared = h.get("x-genio-secret", "") or (query or {}).get("secret", "")
        if not shared:
            return "공유 비밀값이 없어요(주소 뒤에 ?secret=… 를 붙이세요)"
        return None if _eq(secret, shared.strip()) else "공유 비밀값이 맞지 않아요"
    return "지원하지 않는 서비스예요"


# ---------------- 이벤트 읽기 ----------------
@dataclass
class ParsedEvent:
    name: str = ""  # 서비스 이벤트 이름(필터에 쓰는 id 모양)
    label: str = ""
    delivery_id: str = ""
    summary: str = ""
    challenge: str | None = None
    ignore: str | None = None  # 걸러 낸 이유(사람이 읽는 문구)
    keys: list[str] = field(default_factory=list)  # 이벤트 칩과 맞춰 볼 이름들


def _s(v: Any, limit: int = 200) -> str:
    text = " ".join(str(v if v is not None else "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _obj(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _dig(d: Any, *path: str) -> Any:
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def parse_event(
    service: str, headers: dict[str, str], body: dict[str, Any], include_bot: bool = False
) -> ParsedEvent:
    h = {k.lower(): v for k, v in headers.items()}
    ev = ParsedEvent()
    if service == "slack":
        if body.get("type") == "url_verification":
            ev.challenge = str(body.get("challenge") or "")
            return ev
        inner: dict[str, Any] = _obj(body.get("event"))
        kind = str(inner.get("type") or body.get("type") or "")
        ev.name, ev.keys = kind, [kind]
        ev.delivery_id = str(body.get("event_id") or "")
        ev.label = {"message": "Slack 메시지", "app_mention": "Slack @멘션"}.get(
            kind, f"Slack {kind}"
        )
        is_bot = bool(inner.get("bot_id")) or inner.get("subtype") == "bot_message"
        if is_bot and not include_bot:
            ev.ignore = "봇이 보낸 메시지는 건너뛰어요(설정에서 켜면 받아요)"
        who = inner.get("user") or inner.get("username") or "누군가"
        if kind in ("message", "app_mention"):
            ev.summary = f"{_s(who, 40)}: {_s(inner.get('text'), 500)}"
        elif kind == "reaction_added":
            ev.summary = f"{_s(who, 40)}님이 :{_s(inner.get('reaction'), 40)}: 반응을 남겼어요"
        else:
            ev.summary = f"Slack 이벤트 {kind}"
        return ev
    if service == "github":
        kind = h.get("x-github-event", "")
        action = str(body.get("action") or "")
        ev.name = f"{kind}:{action}" if action else kind
        ev.keys = [kind] + ([f"{kind}:{action}"] if action else [])
        ev.label = f"GitHub {ev.name}"
        ev.delivery_id = h.get("x-github-delivery", "")
        if kind == "ping":
            ev.ignore = "연결 확인(ping)이에요"
        repo = _s(_dig(body, "repository", "full_name"), 80)
        if kind == "issues":
            ev.summary = f"이슈 {action}: {_s(_dig(body, 'issue', 'title'))} ({repo})"
        elif kind == "pull_request":
            ev.summary = f"PR {action}: {_s(_dig(body, 'pull_request', 'title'))} ({repo})"
        elif kind == "issue_comment":
            ev.summary = f"댓글: {_s(_dig(body, 'comment', 'body'), 300)} ({repo})"
        elif kind == "push":
            n = len(body.get("commits") or [])
            ev.summary = f"{_s(_dig(body, 'pusher', 'name'), 40)}님이 {_s(body.get('ref'), 80)}에 커밋 {n}개를 올렸어요 ({repo})"
        elif kind == "release":
            ev.summary = f"릴리스 {action}: {_s(_dig(body, 'release', 'name') or _dig(body, 'release', 'tag_name'))} ({repo})"
        else:
            ev.summary = f"GitHub {ev.name} ({repo})"
        return ev
    if service == "shopify":
        topic = h.get("x-shopify-topic", "")
        ev.name, ev.keys, ev.label = topic, [topic], f"Shopify {topic}"
        ev.delivery_id = h.get("x-shopify-webhook-id", "") or h.get("x-shopify-event-id", "")
        if topic.startswith("orders/"):
            ev.summary = (
                f"주문 {_s(body.get('name'), 40)} {_s(body.get('total_price'), 40)} "
                f"{_s(body.get('currency'), 8)}".strip()
            )
        elif topic.startswith("customers/"):
            ev.summary = f"고객 {_s(body.get('email'), 80) or _s(body.get('id'), 40)}"
        else:
            ev.summary = f"Shopify {topic}"
        return ev
    if service == "telegram":
        kinds = [k for k in body if k != "update_id"]
        kind = kinds[0] if kinds else ""
        ev.name, ev.keys, ev.label = kind, [kind], "Telegram 메시지"
        ev.delivery_id = str(body.get("update_id") or "")
        msg: dict[str, Any] = _obj(body.get(kind))
        who = _dig(msg, "from", "first_name") or _dig(msg, "from", "username") or "누군가"
        ev.summary = f"{_s(who, 40)}: {_s(msg.get('text'), 500)}"
        return ev
    if service == "jira":
        kind = str(body.get("webhookEvent") or "")
        ev.name, ev.keys, ev.label = kind, [kind], f"Jira {kind}"
        ev.delivery_id = h.get("x-atlassian-webhook-identifier", "") or (
            f"{body.get('timestamp', '')}:{_dig(body, 'issue', 'key') or ''}:{kind}"
        )
        key = _s(_dig(body, "issue", "key"), 40)
        title = _s(_dig(body, "issue", "fields", "summary"))
        if kind == "comment_created":
            ev.summary = f"{key} 댓글: {_s(_dig(body, 'comment', 'body'), 300)}"
        else:
            ev.summary = f"이슈 {key}: {title}"
        return ev
    if service == "typeform":
        kind = str(body.get("event_type") or "")
        ev.name, ev.keys, ev.label = kind, [kind], "Typeform 응답"
        ev.delivery_id = str(body.get("event_id") or "")
        title = _s(_dig(body, "form_response", "definition", "title"), 80)
        ev.summary = f"설문 응답: {title}" if title else "설문 응답"
        return ev
    raise AppError(422, "알 수 없는 서비스예요.", "자동 실행 설정에서 서비스를 다시 고르세요.")


def passes_filter(events: list[str], ev: ParsedEvent) -> bool:
    """이벤트 칩을 하나도 안 골랐으면 모두 받는다."""
    return not events or any(k in events for k in ev.keys)


# ---------------- 값 연결(받은 값 → 입력 칸) ----------------
def get_path(data: Any, path: str) -> Any:
    """'issue.fields.summary', 'answers[0].text' 같은 위치의 값. 없으면 None."""
    cur = data
    for raw in path.replace("[", ".[").split("."):
        part = raw.strip()
        if not part:
            continue
        if part.startswith("[") and part.endswith("]"):
            try:
                idx = int(part[1:-1])
            except ValueError:
                return None
            if not isinstance(cur, list) or not -len(cur) <= idx < len(cur):
                return None
            cur = cur[idx]
        else:
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
    return cur


def _plain(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        text = json.dumps(v, ensure_ascii=False)
        return text if len(text) <= MAX_VALUE_CHARS else text[:MAX_VALUE_CHARS]
    if isinstance(v, str):
        return v[:MAX_VALUE_CHARS]
    return v


def build_input(
    service: str, ev: ParsedEvent, body: dict[str, Any], mapping: dict[str, str]
) -> dict[str, Any]:
    """실행 입력: message(요약) + service + event + 값 연결로 고른 값들."""
    out: dict[str, Any] = {"message": ev.summary, "service": service, "event": ev.label}
    for key, path in mapping.items():
        val = get_path(body, path)
        out[key] = _plain(val) if val is not None else ""
    return out


def sample_for(preset: Preset) -> tuple[dict[str, str], dict[str, Any]]:
    return dict(preset.sample_headers), json.loads(json.dumps(preset.sample_body))


# ---------------- 같은 알림이 다시 올 때(재전송) 무시 ----------------
_seen_lock = threading.Lock()
_seen: dict[str, float] = {}


def seen_recently(key: str, ttl: int = DEDUPE_SECONDS) -> bool:
    """처음 보면 False(기록해 둠), ttl초 안에 다시 보면 True."""
    client = _client()
    if client is not None:
        try:
            ok = client.set(f"genio:evt:{key}", "1", nx=True, ex=ttl)
            return not ok
        except redis.RedisError:
            pass
    now = time.time()
    with _seen_lock:
        for k in [k for k, t in _seen.items() if t <= now - ttl]:
            del _seen[k]
        if key in _seen:
            return True
        _seen[key] = now
        return False


def reset_seen() -> None:
    with _seen_lock:
        _seen.clear()
