"""AI 연결의 키 목록·돌려쓰기 순서·자동 전환 설정(v0.9) 다루기.

화면과 API가 쓰는 모양을 만들고, 키 추가·수정·삭제와 자동 전환 설정 검사를 한다.
키 값은 응답에 넣지 않는다(끝 4자리만 `****abcd`).
"""

import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.crypto import decrypt_str, encrypt_str, mask
from api.core.errors import AppError, not_found
from api.llm import keypool
from api.llm.chain import DEFAULT_TRIGGERS, MAX_LINKS, merge_triggers
from api.llm.presets import is_rerank
from api.models import LlmProvider, Workspace

STRATEGIES = ("failover", "round_robin", "weighted")
STRATEGY_LABELS = {
    "failover": "앞의 키부터(안 되면 다음 키)",
    "round_robin": "돌아가며",
    "weighted": "비중대로",
}


def _state_view(conn_id: str, key_id: str) -> dict[str, Any]:
    st = keypool.state(conn_id, key_id)
    return {
        "calls": int(st["calls"]),
        "errors": int(st["errors"]),
        "last_error": str(st["last_error"] or ""),
        "cooldown_seconds": int(keypool.cooldown_left(conn_id, key_id)),
    }


def _safe_mask(token: bytes) -> str:
    try:
        return mask(decrypt_str(token))
    except ValueError:
        return "****"


def key_list(row: LlmProvider) -> list[dict[str, Any]]:
    """화면용 키 목록. 첫 번째는 기본 키(끌 수 없음)."""
    out: list[dict[str, Any]] = [
        {
            "id": "primary",
            "label": "기본 키",
            "masked": _safe_mask(row.api_key_encrypted),
            "weight": int(row.primary_weight or 1),
            "disabled": False,
            "primary": True,
            "position": 1,
            **_state_view(row.id, "primary"),
        }
    ]
    for pos, k in enumerate(row.extra_keys or [], start=2):
        if not isinstance(k, dict):
            continue
        out.append(
            {
                "id": str(k.get("id")),
                "label": str(k.get("label") or f"키 {pos}"),
                "masked": _safe_mask(str(k.get("key_encrypted") or "").encode("ascii", "ignore")),
                "weight": int(k.get("weight") or 1),
                "disabled": bool(k.get("disabled")),
                "primary": False,
                "position": pos,
                **_state_view(row.id, str(k.get("id"))),
            }
        )
    return out


def provider_view(p: LlmProvider) -> dict[str, Any]:
    keys = key_list(p)
    return {
        "id": p.id,
        "provider": p.provider,
        "label": p.label,
        "base_url": p.base_url,
        "default_model": p.default_model,
        "is_default": p.is_default,
        "api_key_masked": keys[0]["masked"],
        "rerank": is_rerank(p.provider),
        "key_strategy": p.key_strategy or "failover",
        "keys": keys,
    }


def get_provider(db: Session, ws: str, provider_id: str) -> LlmProvider:
    row = db.get(LlmProvider, provider_id)
    if row is None or row.workspace_id != ws:
        raise not_found("AI 연결")
    return row


def _clean_weight(raw: Any) -> int:
    try:
        w = int(raw)
    except (TypeError, ValueError):
        raise AppError(
            422, "비중은 1~10 사이 숫자예요.", "1(보통)부터 10(많이)까지 고르세요."
        ) from None
    if not 1 <= w <= 10:
        raise AppError(422, "비중은 1~10 사이 숫자예요.", "1(보통)부터 10(많이)까지 고르세요.")
    return w


def add_key(row: LlmProvider, label: str, api_key: str, weight: int = 1) -> str:
    keys = list(row.extra_keys or [])
    if len(keys) + 1 >= keypool.MAX_KEYS:
        raise AppError(
            409,
            f"키는 한 연결에 최대 {keypool.MAX_KEYS}개까지 둘 수 있어요.",
            "안 쓰는 키를 지우고 다시 추가하세요.",
        )
    key_id = secrets.token_hex(4)
    keys.append(
        {
            "id": key_id,
            "label": label.strip()[:60] or f"키 {len(keys) + 2}",
            "key_encrypted": encrypt_str(api_key.strip()).decode("ascii"),
            "weight": _clean_weight(weight),
            "disabled": False,
        }
    )
    row.extra_keys = keys  # 새 목록으로 바꿔야 DB가 변경을 알아챈다
    return key_id


def _find(row: LlmProvider, key_id: str) -> dict[str, Any]:
    for k in row.extra_keys or []:
        if isinstance(k, dict) and k.get("id") == key_id:
            return k
    raise not_found("키")


def update_key(
    row: LlmProvider,
    key_id: str,
    *,
    label: str | None = None,
    weight: int | None = None,
    disabled: bool | None = None,
) -> None:
    if key_id == "primary":
        if disabled:
            raise AppError(
                409,
                "기본 키는 끌 수 없어요.",
                "다른 키를 추가한 뒤, 이 연결을 지우고 다시 만들어 키를 바꾸세요.",
            )
        if weight is not None:
            row.primary_weight = _clean_weight(weight)
        return
    _find(row, key_id)
    keys = [dict(k) for k in (row.extra_keys or []) if isinstance(k, dict)]
    for k in keys:
        if k.get("id") != key_id:
            continue
        if label is not None:
            k["label"] = label.strip()[:60] or k.get("label")
        if weight is not None:
            k["weight"] = _clean_weight(weight)
        if disabled is not None:
            k["disabled"] = bool(disabled)
    row.extra_keys = keys


def delete_key(row: LlmProvider, key_id: str) -> None:
    if key_id == "primary":
        raise AppError(
            409,
            "기본 키는 지울 수 없어요.",
            "연결 전체를 지우고 새로 만들거나, 다른 키를 추가해 비중을 조절하세요.",
        )
    _find(row, key_id)
    row.extra_keys = [
        k for k in (row.extra_keys or []) if not (isinstance(k, dict) and k.get("id") == key_id)
    ]
    keypool.forget(row.id, [key_id])


def key_secret(row: LlmProvider, key_id: str) -> str:
    """연결 테스트처럼 서버 안에서만 쓰는 키 원문."""
    if key_id == "primary":
        return decrypt_str(row.api_key_encrypted)
    k = _find(row, key_id)
    return decrypt_str(str(k.get("key_encrypted") or "").encode("ascii"))


def set_strategy(row: LlmProvider, strategy: str) -> None:
    if strategy not in STRATEGIES:
        raise AppError(
            422, "알 수 없는 돌려쓰기 방식이에요.", "앞의 키부터·돌아가며·비중대로 중에서 고르세요."
        )
    row.key_strategy = strategy


# ---------------- 자동 전환 설정 ----------------
def chat_connections(db: Session, ws: str) -> list[LlmProvider]:
    return [
        r
        for r in db.scalars(
            select(LlmProvider).where(LlmProvider.workspace_id == ws).order_by(LlmProvider.label)
        )
        if not is_rerank(r.provider)
    ]


def clean_fallback(db: Session, ws: str, body: dict[str, Any]) -> dict[str, Any]:
    """저장 전 검사: 연결은 이 워크스페이스의 대화 연결만, 중복 없이, 최대 5개."""
    rows = {r.id: r for r in chat_connections(db, ws)}
    links: list[dict[str, str]] = []
    for link in body.get("links") or []:
        pid = str(link.get("provider_id") or "")
        if pid not in rows:
            raise AppError(
                422,
                "자동 전환 순서에 없는 AI 연결이 들어 있어요.",
                "목록에서 연결을 다시 고르세요(재정렬 전용 연결은 넣을 수 없어요).",
            )
        if any(x["provider_id"] == pid for x in links):
            continue
        links.append({"provider_id": pid, "model": str(link.get("model") or "").strip()[:100]})
    if len(links) > MAX_LINKS:
        raise AppError(
            422, f"자동 전환은 최대 {MAX_LINKS}곳까지 넣을 수 있어요.", "덜 쓰는 연결을 빼 주세요."
        )
    enabled = bool(body.get("enabled"))
    if enabled and not links:
        raise AppError(
            422, "자동 전환 순서가 비어 있어요.", "대체할 AI 연결을 하나 이상 추가한 뒤 켜세요."
        )
    return {"enabled": enabled, "links": links, "triggers": merge_triggers(body.get("triggers"))}


def fallback_view(db: Session, ws: str) -> dict[str, Any]:
    wsr = db.get(Workspace, ws)
    cfg = (wsr.settings or {}).get("llm_fallback") if wsr else None
    cfg = cfg if isinstance(cfg, dict) else {}
    rows = {r.id: r for r in chat_connections(db, ws)}
    links = []
    for link in cfg.get("links") or []:
        r = rows.get(str(link.get("provider_id")))
        links.append(
            {
                "provider_id": str(link.get("provider_id")),
                "label": r.label if r else "(지워진 연결)",
                "provider": r.provider if r else "",
                "model": str(link.get("model") or (r.default_model if r else "")),
                "missing": r is None,
            }
        )
    return {
        "enabled": bool(cfg.get("enabled")),
        "links": links,
        "triggers": merge_triggers(cfg.get("triggers")),
        "default_triggers": dict(DEFAULT_TRIGGERS),
        "connections": [
            {
                "id": r.id,
                "label": r.label,
                "provider": r.provider,
                "default_model": r.default_model,
                "key_count": 1 + len([k for k in (r.extra_keys or []) if not k.get("disabled")]),
            }
            for r in rows.values()
        ],
    }
