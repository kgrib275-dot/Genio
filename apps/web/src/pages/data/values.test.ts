import { columnsProblem, display, fromText, suggestKey, toText } from "@/pages/data/values";

describe("데이터 표 값", () => {
  it("칸 종류에 맞게 읽고 쓴다", () => {
    expect(fromText("1,234", "number")).toEqual({ ok: true, value: 1234 });
    expect(fromText("abc", "number").ok).toBe(false);
    expect(fromText("true", "boolean")).toEqual({ ok: true, value: true });
    expect(fromText('{"a":1}', "json")).toEqual({ ok: true, value: { a: 1 } });
    expect(fromText("{a", "json").ok).toBe(false);
    expect(fromText("2026-11-03", "date")).toEqual({ ok: true, value: "2026-11-03" });
    expect(fromText("  ", "text")).toEqual({ ok: true, value: null });
    expect(toText({ a: 1 }, "json")).toContain('"a": 1');
    expect(toText("2026-11-03T10:00:00Z", "date")).toBe("2026-11-03");
    expect(display(false, "boolean")).toBe("아니오");
    expect(display(1500, "number")).toBe((1500).toLocaleString());
  });

  it("칸 키 검사와 추천", () => {
    expect(columnsProblem([{ key: "name", label: "이름", type: "text" }])).toBeNull();
    expect(columnsProblem([{ key: "1a", label: "x", type: "text" }])).toContain("숫자로 시작");
    expect(
      columnsProblem([
        { key: "a", label: "x", type: "text" },
        { key: "a", label: "y", type: "text" },
      ]),
    ).toContain("두 번");
    expect(suggestKey("Order ID", 0, [])).toBe("order_id");
    expect(suggestKey("주문 번호", 2, [])).toBe("col3");
    expect(suggestKey("email", 0, ["email"])).toBe("email_2");
  });
});
