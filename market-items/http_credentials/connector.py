"""HTTP 인증 정보: 동작 없이 값만 보관한다. HTTP 단계가 인증 방식에 따라 꺼내 쓴다."""

from typing import Any


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    kinds = []
    if secrets.get("token"):
        kinds.append("Bearer 토큰")
    if secrets.get("username"):
        kinds.append("아이디/비밀번호")
    if secrets.get("header_name") and secrets.get("header_value"):
        kinds.append("헤더(" + str(secrets.get("header_name")) + ")")
    if not kinds:
        return {"message": "아직 넣은 인증 값이 없어요. 토큰·아이디/비밀번호·헤더 중 하나를 넣으세요."}
    return {"message": "쓸 수 있는 인증: " + ", ".join(kinds) + ". 실제 호출은 HTTP 단계의 '시험 호출'로 확인하세요."}
