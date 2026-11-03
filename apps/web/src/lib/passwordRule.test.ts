import { describe, expect, it } from "vitest";
import { passwordProblem } from "@/lib/passwordRule";

describe("passwordProblem", () => {
  it("비어 있으면 아무 말도 하지 않는다", () => {
    expect(passwordProblem("")).toBeNull();
  });
  it("짧거나 숫자·영문이 빠지거나 흔하면 알려 준다", () => {
    expect(passwordProblem("ab12")).toContain("8자");
    expect(passwordProblem("abcdefgh")).toContain("영문과 숫자");
    expect(passwordProblem("12345678")).toContain("영문과 숫자");
    expect(passwordProblem("abcd1234")).toContain("흔한");
  });
  it("괜찮은 비밀번호는 통과", () => {
    expect(passwordProblem("Spring2026walk")).toBeNull();
  });
});
