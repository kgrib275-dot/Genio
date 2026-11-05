"""공개 파일 내려받기 링크(v0.9): 서버가 만든 답에 실려 나가는 서명된 짧은 링크.

챗 답이나 입력 폼 결과에 들어 있는 파일만 로그인 없이 내려받을 수 있게, 앱 id·파일 id·만료 시각을
서버 비밀 키로 서명한다(HMAC-SHA256). 서명이 맞고 만료 전이어야 하며, 그 파일이 그 앱의 것인지도
따로 확인한다. 링크는 24시간 안에 만료되고, 지난 대화를 다시 열면 새로 서명해 준다.
"""

import hashlib
import hmac
import time

from api.config import get_settings

LINK_TTL_SECONDS = 24 * 60 * 60
_PURPOSE = "genio-file-link-v1"


def _mac(app_id: str, file_id: str, exp: int) -> str:
    key = get_settings().genio_secret_key.encode()
    msg = f"{_PURPOSE}:{app_id}:{file_id}:{exp}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:40]


def sign(app_id: str, file_id: str, *, ttl: int = LINK_TTL_SECONDS) -> dict[str, str | int]:
    exp = int(time.time()) + ttl
    return {"sig": _mac(app_id, file_id, exp), "exp": exp}


def verify(app_id: str, file_id: str, sig: str, exp: int) -> bool:
    if exp < int(time.time()) or exp > int(time.time()) + LINK_TTL_SECONDS + 60:
        return False
    return hmac.compare_digest(_mac(app_id, file_id, exp), str(sig))
