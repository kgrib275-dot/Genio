// 비밀번호 규칙 안내(서버 core/password_policy.py와 같은 규칙). 서버가 최종 판단한다.
export const PASSWORD_HINT = "8자 이상, 영문과 숫자를 섞어 주세요.";

const COMMON = new Set([
  "12345678",
  "123456789",
  "password",
  "password1",
  "password123",
  "qwerty123",
  "qwer1234",
  "1q2w3e4r",
  "asdf1234",
  "abcd1234",
  "abc12345",
  "admin123",
  "test1234",
]);

/** 문제가 있으면 쉬운 말 한 줄, 없으면 null */
export function passwordProblem(pw: string): string | null {
  if (!pw) return null;
  if (pw.length < 8) return "비밀번호는 8자 이상이어야 해요.";
  if (!/[A-Za-z]/.test(pw) || !/[0-9]/.test(pw)) return "영문과 숫자를 모두 넣어 주세요.";
  if (COMMON.has(pw.toLowerCase())) return "너무 흔한 비밀번호예요. 다른 것으로 정해 주세요.";
  return null;
}
