import { fillRefs, refsIn } from "@/components/canvas/httpPreviewRefs";

test("참조를 찾고 시험용 값으로 바꾼다", () => {
  const url = "https://api.example.com/x?base={{n1.currency}}&q={{ n1.q }}";
  const headers = { "X-Id": "{{n2.id}}" };
  expect(refsIn([url, headers, null])).toEqual(["n1.currency", "n1.q", "n2.id"]);
  expect(fillRefs(url, { "n1.currency": "USD" })).toBe("https://api.example.com/x?base=USD&q=");
  expect(fillRefs({ a: ["{{n2.id}}"] }, { "n2.id": "7" })).toEqual({ a: ["7"] });
});
