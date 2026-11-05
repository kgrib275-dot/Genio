import { coerceFieldValue, simpleFields } from "@/lib/api/v8tools";

test("단순한 도구 입력은 칸으로 바꾼다", () => {
  const fields = simpleFields({
    type: "object",
    properties: {
      query: { type: "string", description: "검색어" },
      limit: { type: "integer" },
      safe: { type: "boolean" },
      mode: { type: "string", enum: ["fast", "deep"] },
    },
    required: ["query"],
  });
  expect(fields?.map((f) => [f.name, f.kind, f.required])).toEqual([
    ["query", "text", true],
    ["limit", "number", false],
    ["safe", "boolean", false],
    ["mode", "choice", false],
  ]);
  expect(fields?.[3]?.options).toEqual(["fast", "deep"]);
  expect(fields?.[0]?.description).toBe("검색어");
});

test("복잡하거나 비어 있는 입력은 JSON으로 입력하게 null", () => {
  expect(simpleFields(undefined)).toBeNull();
  expect(simpleFields({ type: "object" })).toBeNull();
  expect(simpleFields({ type: "object", properties: {} })).toBeNull();
  expect(simpleFields({ type: "object", properties: { items: { type: "array" } } })).toBeNull();
  expect(simpleFields({ type: "object", properties: { cfg: { type: "object" } } })).toBeNull();
  const many = Object.fromEntries(
    Array.from({ length: 16 }, (_, i) => [`f${i}`, { type: "string" }]),
  );
  expect(simpleFields({ type: "object", properties: many })).toBeNull();
});

test("칸에 적은 글을 형에 맞게 바꾸고 {{ }}는 그대로 둔다", () => {
  expect(coerceFieldValue("number", "12")).toBe(12);
  expect(coerceFieldValue("number", "열두")).toBe("열두");
  expect(coerceFieldValue("boolean", "true")).toBe(true);
  expect(coerceFieldValue("boolean", "false")).toBe(false);
  expect(coerceFieldValue("text", "안녕")).toBe("안녕");
  expect(coerceFieldValue("number", "{{n1.count}}")).toBe("{{n1.count}}");
  expect(coerceFieldValue("text", "")).toBeUndefined();
});
