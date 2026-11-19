"""개인정보 가리기(운영 준비 1차 B2).

한국에서 흔한 개인정보 모양을 찾아 가린다.
  주민등록번호·외국인등록번호, 휴대폰·전화번호, 카드번호(Luhn 검사), 계좌번호(하이픈 있는 모양),
  이메일, 여권번호
두 가지로 쓴다.
  mask(text)               기록 화면·내보내기·외부 추적: "[전화번호]"처럼 종류만 남긴다(되돌릴 수 없음)
  mask_reversible(text)    AI로 보내기 전: "[전화번호1]"로 바꾸고, AI 답에 그 표시가 있으면 unmask로 원래 값을 돌려 넣는다
워크스페이스 설정 settings["privacy"]:
  mask_logs        실행 기록·대화 로그·내보내기·외부 추적에서 가린다(기본 꺼짐)
  mask_before_ai   모든 AI 호출 전에 가리고, 답에서 되돌린다(기본 꺼짐). AI 단계마다 따로 켤 수도 있다
"""

import re
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

# (종류 이름, 패턴, 추가 검사). 순서가 중요하다: 긴·구체적인 모양을 먼저 찾는다.
_RRN = re.compile(r"(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\s?-?\s?[1-8]\d{6}(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_MOBILE = re.compile(r"(?<!\d)01[016789][ -.]?\d{3,4}[ -.]?\d{4}(?!\d)")
_PHONE = re.compile(r"(?<!\d)0(?:2|[3-6][1-5]|70|50\d?)[ -.]?\d{3,4}[ -.]?\d{4}(?!\d)")
_ACCOUNT = re.compile(r"(?<![\d-])\d{2,6}-\d{2,6}-\d{2,8}(?:-\d{1,3})?(?![\d-])")
_PASSPORT = re.compile(r"(?<![A-Za-z0-9])[MSRODG]\d{3}[A-Z]?\d{4,5}(?![A-Za-z0-9])")


def _luhn(raw: str) -> bool:
    digits = [int(c) for c in raw if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _date_like(raw: str) -> bool:
    """2026-11-18 같은 날짜는 계좌번호로 보지 않는다."""
    parts = raw.split("-")
    return len(parts) == 3 and len(parts[0]) == 4 and parts[0].startswith(("19", "20"))


KINDS: list[tuple[str, re.Pattern[str], Callable[[str], bool] | None]] = [
    ("주민등록번호", _RRN, None),
    ("카드번호", _CARD, _luhn),
    ("이메일", _EMAIL, None),
    ("전화번호", _MOBILE, None),
    ("전화번호", _PHONE, None),
    ("계좌번호", _ACCOUNT, lambda s: not _date_like(s)),
    ("여권번호", _PASSPORT, None),
]


def _replace(text: str, repl: Callable[[str, str], str]) -> str:
    out = text
    for kind, pat, check in KINDS:

        def sub(m: re.Match[str], kind: str = kind, check: Any = check) -> str:
            found = m.group(0)
            if check is not None and not check(found):
                return found
            return repl(kind, found)

        out = pat.sub(sub, out)
    return out


def count_kinds(text: str) -> dict[str, int]:
    """글에 든 개인정보 종류별 개수(이메일·전화 같은 흔한 것까지 모두 센다)."""
    found: dict[str, int] = {}

    def note(kind: str, found_text: str) -> str:
        found[kind] = found.get(kind, 0) + 1
        return found_text

    if text:
        _replace(text, note)
    return found


def mask(text: str) -> str:
    """개인정보를 '[종류]'로 바꾼다(되돌리지 않음)."""
    if not text:
        return text
    return _replace(text, lambda kind, _found: f"[{kind}]")


def mask_value(value: Any) -> Any:
    """dict·list 안의 글까지 모두 가린다(실행 기록 값 등)."""
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, list):
        return [mask_value(v) for v in value]
    if isinstance(value, dict):
        return {k: mask_value(v) for k, v in value.items()}
    return value


class Vault:
    """AI로 보내기 전에 가린 값을 기억했다가 답에서 되돌린다. 같은 값은 같은 표시를 쓴다."""

    def __init__(self) -> None:
        self.by_token: dict[str, str] = {}
        self.by_value: dict[str, str] = {}
        self.counts: dict[str, int] = {}

    def mask(self, text: str) -> str:
        if not text:
            return text

        def repl(kind: str, found: str) -> str:
            if found in self.by_value:
                return self.by_value[found]
            n = self.counts.get(kind, 0) + 1
            self.counts[kind] = n
            token = f"[{kind}{n}]"
            self.by_token[token] = found
            self.by_value[found] = token
            return token

        return _replace(text, repl)

    def unmask(self, text: str) -> str:
        if not text or not self.by_token:
            return text
        out = text
        for token, value in self.by_token.items():
            out = out.replace(token, value)
        return out

    def unmask_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.unmask(value)
        if isinstance(value, list):
            return [self.unmask_value(v) for v in value]
        if isinstance(value, dict):
            return {k: self.unmask_value(v) for k, v in value.items()}
        return value

    def __bool__(self) -> bool:
        return bool(self.by_token)


# ---------------- 워크스페이스 설정 ----------------
DEFAULTS: dict[str, bool] = {"mask_logs": False, "mask_before_ai": False}


def get_privacy(db: Session, workspace_id: str | None) -> dict[str, bool]:
    from api.models import Workspace

    ws = db.get(Workspace, workspace_id) if workspace_id else None
    saved = ((ws.settings or {}).get("privacy") or {}) if ws else {}
    return {k: bool(saved.get(k, v)) for k, v in DEFAULTS.items()}


def logs_masked(db: Session, workspace_id: str | None) -> bool:
    return get_privacy(db, workspace_id)["mask_logs"]
