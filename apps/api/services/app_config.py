"""앱 기능(App Toolkit) 기본값과 앱 환경 값(비밀 암호화·마스킹)."""

import copy
import re
from typing import Any

from api.core.crypto import decrypt_str, encrypt_str, mask

DEFAULT_FEATURES: dict[str, Any] = {
    "opening_statement": "",
    "suggested_questions": [],
    "follow_up": {"enabled": False},
    "citations": {"enabled": True},
    "moderation": {
        "enabled": False,
        "keywords": [],
        "preset_reply": "그 내용에는 답할 수 없어요.",
        "check_output": False,
    },
    "annotation_reply": {"enabled": False, "score_threshold": 0.85},
    "speech": {"stt": False, "tts": False},
    "file_upload": {"enabled": False, "max_files": 3},
    # v0.6: summary=True면 기억 창보다 오래된 대화를 AI가 요약해 함께 넘긴다
    "memory": {"window": 6, "summary": False},
    # v0.4: 실패하면 실행할 앱(n8n Error Workflow). 같은 워크스페이스의 앱 id
    "on_failure": {"app_id": None},
    # v0.5: 상담원 전환(기능 정의서 S7). 이 말이 들어오거나 '상담원 연결'을 누르면 사람에게 넘긴다
    "handoff": {
        "enabled": False,
        "keywords": ["상담원", "사람이랑", "직원 연결"],
        "message": "상담원을 연결해 드릴게요. 잠시만 기다려 주세요. 이어서 적으신 말도 상담원에게 전달돼요.",
    },
    # v0.6: MCP 서버로 게시(ADR 0010). tool_name은 영문·숫자·_-만(비우면 앱 이름에서 만든다)
    "mcp": {"enabled": False, "tool_name": "", "description": ""},
}


def merged_features(saved: dict[str, Any] | None) -> dict[str, Any]:
    """저장된 기능 설정을 기본값 위에 덮는다(한 단계 깊이까지)."""
    out = copy.deepcopy(DEFAULT_FEATURES)
    for k, v in (saved or {}).items():
        if k not in out:
            continue
        if isinstance(out[k], dict) and isinstance(v, dict):
            out[k].update({kk: vv for kk, vv in v.items() if kk in out[k]})
        else:
            out[k] = v
    return out


def patch_features(saved: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    current = merged_features(saved)
    for k, v in patch.items():
        if k not in current:
            continue
        if isinstance(current[k], dict) and isinstance(v, dict):
            current[k].update({kk: vv for kk, vv in v.items() if kk in current[k]})
        else:
            current[k] = v
    current["suggested_questions"] = [
        str(q) for q in current["suggested_questions"] if str(q).strip()
    ][:6]
    current["moderation"]["keywords"] = [
        str(w) for w in current["moderation"]["keywords"] if str(w).strip()
    ][:200]
    current["memory"]["window"] = max(0, min(int(current["memory"]["window"] or 0), 20))
    current["memory"]["summary"] = bool(current["memory"].get("summary"))
    current["file_upload"]["max_files"] = max(
        1, min(int(current["file_upload"]["max_files"] or 1), 10)
    )
    current["handoff"]["keywords"] = [
        str(w).strip()[:30] for w in current["handoff"]["keywords"] if str(w).strip()
    ][:30]
    current["handoff"]["message"] = str(current["handoff"]["message"] or "")[:300]
    target = current["on_failure"].get("app_id")
    current["on_failure"]["app_id"] = (str(target).strip()[:36] or None) if target else None
    mcp_name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(current["mcp"]["tool_name"] or "")).strip("_")
    current["mcp"]["tool_name"] = mcp_name[:64]
    current["mcp"]["enabled"] = bool(current["mcp"]["enabled"])
    current["mcp"]["description"] = str(current["mcp"]["description"] or "")[:1000]
    thr = float(current["annotation_reply"]["score_threshold"] or 0.85)
    current["annotation_reply"]["score_threshold"] = max(0.5, min(thr, 1.0))
    return current


# ---------------- 환경 값 ----------------
# 저장 형식: [{"key", "secret": bool, "value"(비밀 아님) | "value_enc"(비밀)}]


def decrypt_env_vars(stored: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for v in stored:
        key = str(v.get("key") or "")
        if not key:
            continue
        if v.get("secret") and v.get("value_enc"):
            try:
                out[key] = decrypt_str(str(v["value_enc"]).encode("ascii"))
            except ValueError:
                out[key] = ""
        else:
            out[key] = v.get("value", "")
    return out


def public_env_vars(stored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """응답용: 비밀 값은 마스킹."""
    plain = decrypt_env_vars(stored)
    return [
        {
            "key": v.get("key"),
            "secret": bool(v.get("secret")),
            "value": mask(str(plain.get(str(v.get("key")), "")))
            if v.get("secret")
            else v.get("value", ""),
        }
        for v in stored
        if v.get("key")
    ]


def store_env_vars(
    incoming: list[dict[str, Any]], previous: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """비밀 값이 '****'로 시작하면(마스킹된 값을 그대로 돌려보낸 것) 기존 값을 유지한다."""
    prev = {str(v.get("key")): v for v in previous}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for v in incoming:
        key = str(v.get("key") or "").strip()
        if not key or key in seen or not key.replace("_", "").isalnum():
            continue
        seen.add(key)
        value = str(v.get("value") or "")
        if v.get("secret"):
            if value.startswith("****") and prev.get(key, {}).get("value_enc"):
                out.append({"key": key, "secret": True, "value_enc": prev[key]["value_enc"]})
            else:
                out.append(
                    {"key": key, "secret": True, "value_enc": encrypt_str(value).decode("ascii")}
                )
        else:
            out.append({"key": key, "secret": False, "value": value})
    return out
