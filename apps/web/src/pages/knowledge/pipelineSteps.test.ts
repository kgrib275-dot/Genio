import { formatPairs, normalizePipeline, parsePairs } from "@/pages/knowledge/pipelineSteps";

test("처리 순서를 정해진 순서로 맞추고 항상 도는 단계는 켠다", () => {
  const p = normalizePipeline([
    { type: "store", enabled: false },
    { type: "clean", enabled: true, mask_urls: true },
  ]);
  expect(p.map((s) => s.type)).toEqual(["extract", "clean", "split", "metadata", "store"]);
  expect(p[4]?.enabled).toBe(true);
  expect(p[1]).toMatchObject({ enabled: true, mask_urls: true, collapse_spaces: true });
  expect(p[3]?.enabled).toBe(false);
});

test("꼬리표 글과 묶음을 오간다", () => {
  expect(parsePairs("부서=인사, 연도 = 2026, 잘못된")).toEqual({ 부서: "인사", 연도: "2026" });
  expect(formatPairs({ 부서: "인사" })).toBe("부서=인사");
});
