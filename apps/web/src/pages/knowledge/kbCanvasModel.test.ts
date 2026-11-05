import type { CanvasPreview, Stage } from "@/lib/api/kbcanvas";
import {
  aiWarning,
  buildFlow,
  flowHeadline,
  stageSummary,
  usdText,
  type FlowNode,
} from "@/pages/knowledge/kbCanvasModel";
import { normalizePipeline } from "@/pages/knowledge/pipelineSteps";

const ctx = { docs: 3, mode: "general" as const };

const preview: CanvasPreview = {
  total: 42,
  chunks: [],
  metadata: {},
  log: [],
  text_preview: "",
  chunk_mode: "general",
  ai_calls: 5,
  stages: {
    extract: { chars: 12345 },
    clean: { enabled: true, before_chars: 12345, after_chars: 11000 },
    split: { chunks: 40, mode: "general" },
    translate: { enabled: true, language: "영어", calls: 3, calls_full: 40 },
    summarize: { enabled: true, skipped: "이번 달 AI 사용 한도를 다 썼어요." },
    metadata: { enabled: true, tags: { 부서: "인사", 연도: "2026" } },
    image: { enabled: true, images: 4, described: 3 },
    store: { chunks: 42 },
  },
};

test("미리 보기 전에는 문서 수와 설정을, 후에는 실제 숫자를 보여 준다", () => {
  const steps = normalizePipeline([
    { type: "clean", enabled: true } as never,
    { type: "translate", enabled: true } as never,
  ]);
  const get = (t: string): Stage => steps.find((s) => s.type === t) as Stage;
  expect(stageSummary(get("extract"), undefined, ctx)).toBe("문서 3개");
  expect(stageSummary(get("split"), undefined, ctx)).toBe("일반 방식");
  expect(stageSummary(get("translate"), undefined, ctx)).toBe("영어로 번역");
  expect(stageSummary(get("summarize"), undefined, ctx)).toBe("꺼짐");
  expect(flowHeadline(undefined, ctx)).toContain("문서 3개");

  expect(stageSummary(get("extract"), preview, ctx)).toBe("글 12,345자");
  expect(stageSummary(get("clean"), preview, ctx)).toBe("12,345자 → 11,000자");
  expect(stageSummary(get("split"), preview, ctx)).toBe("조각 40개");
  expect(stageSummary(get("translate"), preview, ctx)).toBe("영어 · AI 3번");
  expect(stageSummary(get("store"), preview, ctx)).toBe("조각 42개");
  expect(flowHeadline(preview, ctx)).toBe("문서 3개 → (미리 본 문서에서) 조각 42개");
});

test("건너뛴 AI 단계와 이미지·꼬리표 요약", () => {
  const steps = normalizePipeline([
    { type: "summarize", enabled: true } as never,
    { type: "metadata", enabled: true } as never,
    { type: "image", enabled: true } as never,
  ]);
  const get = (t: string): Stage => steps.find((s) => s.type === t) as Stage;
  expect(stageSummary(get("summarize"), preview, ctx)).toBe("건너뜀");
  expect(stageSummary(get("metadata"), preview, ctx)).toBe("꼬리표 2개");
  expect(stageSummary(get("image"), preview, ctx)).toBe("그림 4장 → 설명 3개");
});

test("캔버스는 노드 8개와 연결선 7개, 선택·상태가 표시된다", () => {
  const steps = normalizePipeline([{ type: "image", enabled: true } as never]);
  const { nodes, edges } = buildFlow(steps, undefined, ctx, "image");
  expect(nodes).toHaveLength(8);
  expect(edges).toHaveLength(7);
  expect(nodes.map((n) => n.id)).toEqual([
    "extract",
    "clean",
    "split",
    "translate",
    "summarize",
    "metadata",
    "image",
    "store",
  ]);
  expect(nodes.find((n) => n.id === "image")?.data).toMatchObject({
    selected: true,
    status: "on",
    ai: true,
    index: 7,
  });
  expect(nodes.find((n) => n.id === "extract")?.data.status).toBe("always");
  expect(nodes.find((n) => n.id === "clean")?.data.status).toBe("off");
  expect((nodes[1] as FlowNode).position.x).toBeGreaterThan((nodes[0] as FlowNode).position.x);
  expect(edges.every((e) => !e.animated)).toBe(true); // 미리 보기 전에는 움직이지 않는다
});

test("AI 안내 문구와 비용 표기", () => {
  expect(aiWarning([])).toBeNull();
  expect(aiWarning(["translate", "image"])).toContain("번역·이미지 설명");
  expect(usdText(null)).toBe("알 수 없음");
  expect(usdText(0.004)).toBe("$0.01 미만");
  expect(usdText(1.234)).toBe("$1.23");
});
