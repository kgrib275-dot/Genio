import { hasTokens } from "@/lib/api/account";
import { deviceName } from "@/lib/deviceName";

test("로그인 결과: 토큰이 있을 때만 바로 로그인", () => {
  expect(hasTokens({ access_token: "a", refresh_token: "r", token_type: "bearer" })).toBe(true);
  expect(hasTokens({ mfa_required: true, mfa_token: "m" })).toBe(false);
  expect(hasTokens({ verify_required: true, email: "a@b.c" })).toBe(false);
});

test("기기 이름을 쉬운 말로", () => {
  expect(
    deviceName(
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
    ),
  ).toBe("Windows · Chrome");
  expect(deviceName("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) Safari/604.1")).toBe(
    "iPhone·iPad · Safari",
  );
  expect(deviceName("")).toBe("알 수 없는 기기");
});
