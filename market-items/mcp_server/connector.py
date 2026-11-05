"""MCP 서버 연결 정보: 동작 없이 주소와 토큰만 보관한다.

연결 테스트(도구 목록 불러오기)는 플랫폼이 직접 처리하므로 여기 test()는 쓰이지 않고,
설명용으로만 둔다.
"""

from typing import Any


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    return {"message": "연결 정보 화면의 'MCP 서버'에서 연결 테스트로 도구 목록을 확인하세요."}
