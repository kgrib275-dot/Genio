import {
  columnsProblem,
  display,
  fromText,
  parsePastedTable,
  suggestKey,
  toCsv,
  toText,
} from "@/pages/data/values";

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

describe("엑셀에서 붙여 넣은 표", () => {
  const text =
    ["이름", "부서", "금액", "입사일"].join("\t") +
    "\n" +
    ["김하나", "인사팀", "1,200", "2026.1.5"].join("\t") +
    "\n" +
    ["이둘", "총무팀", "300", "2026-02-10"].join("\t");
  it("첫 줄을 칸 이름으로, 값 모양으로 종류를 짐작한다", () => {
    const t = parsePastedTable(text);
    expect(t?.columns.map((c) => [c.label, c.type])).toEqual([
      ["이름", "text"],
      ["부서", "text"],
      ["금액", "number"],
      ["입사일", "date"],
    ]);
    expect(t?.columns.map((c) => c.key)).toEqual(["col1", "col2", "col3", "col4"]);
    expect(t?.rows[0]).toEqual(["김하나", "인사팀", "1200", "2026-01-05"]);
  });
  it("쉼표로 나뉜 글과 빈 입력도 다룬다", () => {
    expect(parsePastedTable("a,b\n1,2")?.columns.map((c) => c.key)).toEqual(["a", "b"]);
    expect(parsePastedTable("   ")).toBeNull();
  });
  it("CSV로 바꿀 때 쉼표·따옴표를 감싼다", () => {
    const csv = toCsv([{ key: "a", label: "A", type: "text" }], [['x,"y"']]);
    expect(csv).toBe('a\n"x,""y"""');
  });
});
