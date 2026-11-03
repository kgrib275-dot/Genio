"""SSO 인터페이스(설계서 §1: 프로토타입은 SSO 없음, 인터페이스만 남김).

정식 버전에서 SAML·OIDC 공급자를 붙일 때 이 Protocol을 구현해 등록한다.
로그인 흐름: authorize_url → (공급자 로그인) → exchange_code → SsoIdentity → 사용자 찾기/만들기 → create_tokens.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SsoIdentity:
    provider: str
    subject: str
    email: str
    name: str


class SsoProvider(Protocol):
    key: str

    def authorize_url(self, *, state: str, redirect_uri: str) -> str: ...

    def exchange_code(self, *, code: str, redirect_uri: str) -> SsoIdentity: ...


PROVIDERS: dict[str, SsoProvider] = {}


def register(provider: SsoProvider) -> None:
    PROVIDERS[provider.key] = provider
