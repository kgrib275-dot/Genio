"""비밀번호 규칙(부하 시험 보고서 §4): 8자 이상, 영문과 숫자를 모두, 너무 흔한 비밀번호는 안 됨.

새로 정할 때(가입·초대 수락·비밀번호 바꾸기·관리자 직접 지정)에만 검사한다. 기존 비밀번호로
로그인하는 것은 막지 않는다.
"""

import re

from api.core.errors import AppError

COMMON = {
    "12345678",
    "123456789",
    "1234567890",
    "password",
    "password1",
    "password12",
    "password123",
    "qwerty123",
    "qwer1234",
    "1q2w3e4r",
    "1q2w3e4r!",
    "asdf1234",
    "abcd1234",
    "abc12345",
    "admin123",
    "admin1234",
    "iloveyou1",
    "11111111",
    "00000000",
    "a1234567",
    "test1234",
    "welcome1",
    "letmein1",
}


def password_problem(pw: str, email: str | None = None) -> str | None:
    if len(pw) < 8:
        return "비밀번호는 8자 이상이어야 해요."
    if len(pw) > 128:
        return "비밀번호는 128자까지 쓸 수 있어요."
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"[0-9]", pw):
        return "비밀번호에 영문과 숫자를 모두 넣어 주세요."
    if pw.lower() in COMMON:
        return "너무 흔한 비밀번호예요."
    if email and pw.lower() == email.split("@")[0].lower():
        return "이메일 아이디와 같은 비밀번호는 쓸 수 없어요."
    return None


def check_password(pw: str, email: str | None = None) -> None:
    problem = password_problem(pw, email)
    if problem:
        raise AppError(
            422,
            problem,
            "8자 이상, 영문과 숫자를 섞어 남이 짐작하기 어렵게 정하세요(예: 봄날2026산책).",
        )
