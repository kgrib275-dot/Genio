import { parseTestValue, testValueText } from "@/lib/api/nodeTest";

test("입력칸 글을 원래 값 형식으로 되돌린다", () => {
  expect(parseTestValue("12", "number")).toBe(12);
  expect(parseTestValue("많이", "number")).toBe("많이");
  expect(parseTestValue("", "number")).toBe("");
  expect(parseTestValue("예", "boolean")).toBe(true);
  expect(parseTestValue("false", "boolean")).toBe(false);
  expect(parseTestValue('{"a":1}', "json")).toEqual({ a: 1 });
  expect(parseTestValue("{깨진", "json")).toBe("{깨진");
  expect(parseTestValue("안녕", "string")).toBe("안녕");
});

test("값을 입력칸 글로 바꾼다", () => {
  expect(testValueText(null)).toBe("");
  expect(testValueText(5)).toBe("5");
  expect(testValueText("가")).toBe("가");
  expect(testValueText({ a: [1] })).toBe('{"a":[1]}');
});
