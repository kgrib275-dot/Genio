import { safeNext } from "@/lib/nav";

test("사이트 안의 경로만 돌아갈 주소로 쓴다", () => {
  expect(safeNext("/apps/1/builder?x=1#a")).toBe("/apps/1/builder?x=1#a");
  expect(safeNext("/")).toBe("/");
});

test("외부로 나가는 주소는 첫 화면으로 바꾼다", () => {
  for (const bad of [
    null,
    "",
    "https://evil.example",
    "//evil.example",
    "/\\evil.example",
    "/\\/evil.example",
    "\\\\evil.example",
    "/\t/evil.example",
    "/\n/evil.example",
    "/\r/evil.example",
    "evil.example",
    "javascript:alert(1)",
  ]) {
    expect(safeNext(bad as string | null)).toBe("/");
  }
});
