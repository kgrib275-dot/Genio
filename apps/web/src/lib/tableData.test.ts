import { describe, expect, it } from "vitest";
import { findTable, toCsv } from "./tableData";

describe("tableData", () => {
  it("목록을 찾고 CSV로 바꾼다(따옴표·수식 방어)", () => {
    const t = findTable({
      result: { rows: [{ 이름: "김, 철수", 메모: "=1+1" }, { 이름: "이영희" }] },
    });
    expect(t?.columns).toEqual(["이름", "메모"]);
    const csv = toCsv(t ?? { columns: [], rows: [] });
    expect(csv.startsWith("\ufeff이름,메모")).toBe(true);
    expect(csv).toContain('"김, 철수",\'=1+1');
    expect(csv).toContain("이영희,");
  });
  it("항목이 1개거나 섞여 있으면 표로 보지 않는다", () => {
    expect(findTable([{ a: 1 }])).toBeNull();
    expect(findTable([{ a: 1 }, 3])).toBeNull();
    expect(findTable("글")).toBeNull();
  });
});
