import { ALL_DEPARTMENT, DEPARTMENTS, filterTemplatesByDepartment } from "@/lib/departments";

const templates = [
  { key: "tpl_doc_summary" },
  { key: "biz_quote_request" },
  { key: "biz_weekly_report" },
  { key: "unknown_item" },
];

describe("부서별 템플릿", () => {
  it("전체이거나 모르는 부서면 그대로 둔다", () => {
    expect(filterTemplatesByDepartment(templates, ALL_DEPARTMENT)).toHaveLength(4);
    expect(filterTemplatesByDepartment(templates, "none")).toHaveLength(4);
  });
  it("부서에 속한 것만 정해 둔 순서대로 남긴다", () => {
    expect(filterTemplatesByDepartment(templates, "report").map((t) => t.key)).toEqual([
      "biz_weekly_report",
      "tpl_doc_summary",
    ]);
    expect(filterTemplatesByDepartment(templates, "sales").map((t) => t.key)).toEqual([
      "biz_quote_request",
    ]);
  });
  it("모든 부서에 예시 문장이 셋씩 있다", () => {
    for (const d of DEPARTMENTS) expect(d.examples).toHaveLength(3);
  });
});
