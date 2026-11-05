import {
  enabledAiStages,
  formatPairs,
  normalizePipeline,
  parsePairs,
  templateToDraft,
} from "@/pages/knowledge/pipelineSteps";

test("처리 순서를 8단계 정해진 순서로 맞추고 항상 도는 단계는 켠다", () => {
  const p = normalizePipeline([
    { type: "store", enabled: false } as never,
    { type: "clean", enabled: true, mask_urls: true } as never,
  ]);
  expect(p.map((s) => s.type)).toEqual([
    "extract",
    "clean",
    "split",
    "translate",
    "summarize",
    "metadata",
    "image",
    "store",
  ]);
  expect(p[7]?.enabled).toBe(true);
  expect(p[1]).toMatchObject({ enabled: true, mask_urls: true, collapse_spaces: true });
  expect(p[5]?.enabled).toBe(false);
  // AI를 부르는 단계는 기본이 꺼져 있다
  expect(enabledAiStages(p)).toEqual([]);
  expect(p[3]).toMatchObject({ enabled: false, target_language: "영어" });
  expect(p[6]).toMatchObject({ enabled: false, max_images: 20, min_size: 100 });
});

test("켜진 AI 단계만 비용 안내에 올라간다", () => {
  const p = normalizePipeline([
    { type: "translate", enabled: true } as never,
    { type: "image", enabled: true } as never,
    { type: "clean", enabled: true } as never,
  ]);
  expect(enabledAiStages(p)).toEqual(["translate", "image"]);
});

test("꼬리표 글과 묶음을 오간다", () => {
  expect(parsePairs("부서=인사, 연도 = 2026, 잘못된")).toEqual({ 부서: "인사", 연도: "2026" });
  expect(formatPairs({ 부서: "인사" })).toBe("부서=인사");
});

test("모음을 고르면 처리 순서와 나누기 설정이 통째로 바뀐다", () => {
  const draft = templateToDraft({
    settings: {
      chunk_mode: "parent_child",
      chunk_size: 1000,
      pipeline: [{ type: "clean", enabled: true, remove_repeated_lines: true }],
    },
  });
  expect(draft.steps).toHaveLength(8);
  expect(draft.steps[1]).toMatchObject({ enabled: true, remove_repeated_lines: true });
  expect(draft.overrides).toEqual({ chunk_mode: "parent_child", chunk_size: 1000 });
});
