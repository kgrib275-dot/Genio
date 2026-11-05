import { flattenValue, matchesQuery, refPath } from "@/lib/valueFlatten";

test("겹친 값을 경로 목록으로 펼치고 내부 값(__)은 뺀다", () => {
  const rows = flattenValue({
    text: "안녕",
    n: 3,
    ok: true,
    nothing: null,
    body: { rates: { KRW: 1503.12 }, date: "2026-11-05" },
    items: [{ name: "a" }, { name: "b" }],
    __conv_set: { x: 1 },
  });
  const by = Object.fromEntries(rows.map((r) => [r.path, r]));
  expect(by["text"]?.text).toBe("안녕");
  expect(by["n"]?.kind).toBe("number");
  expect(by["ok"]?.text).toBe("예");
  expect(by["nothing"]?.kind).toBe("empty");
  expect(by["body.rates.KRW"]?.text).toBe("1503.12");
  expect(by["items"]?.text).toBe("목록 2개");
  expect(by["items[1].name"]?.text).toBe("b");
  expect(Object.keys(by).some((p) => p.startsWith("__"))).toBe(false);
});

test("긴 목록은 앞 5개만 펼치고 나머지는 생략 표시", () => {
  const rows = flattenValue({ xs: [1, 2, 3, 4, 5, 6, 7] });
  expect(rows.map((r) => r.path)).toContain("xs[4]");
  expect(rows.map((r) => r.path)).not.toContain("xs[5]");
  expect(rows.at(-1)?.text).toBe("나머지 2개는 생략");
});

test("값 끌어오기 경로와 검색", () => {
  expect(refPath("n2", "body.rates.KRW")).toBe("{{n2.body.rates.KRW}}");
  const item = { path: "body.date", text: "2026-11-05", kind: "string" as const };
  expect(matchesQuery(item, "DATE")).toBe(true);
  expect(matchesQuery(item, "2026-11")).toBe(true);
  expect(matchesQuery(item, "없는말")).toBe(false);
  expect(matchesQuery(item, "  ")).toBe(true);
});
