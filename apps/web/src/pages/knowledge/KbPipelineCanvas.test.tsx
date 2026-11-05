import { render, screen } from "@testing-library/react";
import type { CanvasPreview } from "@/lib/api/kbcanvas";
import { imageReportText } from "@/lib/kbImageSource";
import { StagePreview } from "@/pages/knowledge/KbPipelineCanvas";

const preview: CanvasPreview = {
  total: 5,
  chunks: [
    {
      index: 3,
      content: "[그림 2쪽] 매출 막대그래프",
      parent_content: null,
      char_count: 12,
      kind: "image",
      image: { caption: "매출 막대그래프", page: 2, index: 0 },
      thumb: "data:image/png;base64,AAAA",
    },
  ],
  metadata: {},
  log: ["글 100자를 꺼냈어요."],
  text_preview: "",
  chunk_mode: "general",
  ai_calls: 4,
  stages: {
    extract: { chars: 1234, sample: "연차 규정 본문" },
    clean: {
      enabled: true,
      before_chars: 120,
      after_chars: 100,
      before_sample: "정리 전 글",
      after_sample: "정리 후 글",
    },
    translate: {
      enabled: true,
      language: "영어",
      calls: 3,
      calls_full: 12,
      estimated_cost_usd: 0.05,
      samples: [{ before: "연차는 15일", after: "Annual leave is 15 days" }],
    },
    summarize: { enabled: true, skipped: "이번 달 AI 사용 한도를 다 썼어요." },
    image: { enabled: true, images: 4, described: 3, calls: 3, calls_full: 4, cut: 1 },
  },
};

test("미리 보기 전에는 안내 문구를 보여 준다", () => {
  render(<StagePreview type="clean" preview={undefined} />);
  expect(screen.getByText(/미리 보기/)).toBeTruthy();
});

test("정리 단계는 정리 전·후 글을 나란히 보여 준다", () => {
  render(<StagePreview type="clean" preview={preview} />);
  expect(screen.getByText("정리 전 글")).toBeTruthy();
  expect(screen.getByText("정리 후 글")).toBeTruthy();
});

test("번역 단계는 AI 호출 수와 예상 비용, 번역 전후를 보여 준다", () => {
  render(<StagePreview type="translate" preview={preview} />);
  expect(screen.getByText(/전부 다시 나누면 약 12번/)).toBeTruthy();
  expect(screen.getByText("Annual leave is 15 days")).toBeTruthy();
});

test("건너뛴 AI 단계는 이유를 보여 준다", () => {
  render(<StagePreview type="summarize" preview={preview} />);
  expect(screen.getByText("이번 달 AI 사용 한도를 다 썼어요.")).toBeTruthy();
});

test("이미지 설명 단계는 썸네일과 설명, 3장까지만 미리 봤다는 안내를 보여 준다", () => {
  render(<StagePreview type="image" preview={preview} />);
  expect(screen.getByText("그림 4장")).toBeTruthy();
  expect(screen.getByText("설명 3개")).toBeTruthy();
  expect(screen.getByText(/미리 보기는 3장까지\(1장 더 있음\)/)).toBeTruthy();
  const img = screen.getByAltText("매출 막대그래프") as HTMLImageElement;
  expect(img.src.startsWith("data:image/png")).toBe(true);
  expect(screen.getByText(/2쪽/)).toBeTruthy();
});

test("문서별 그림 보고 글", () => {
  expect(imageReportText({ images: 3, described: 3, calls: 3 })).toMatchObject({
    text: "그림 3/3장 설명",
    tone: "green",
  });
  expect(
    imageReportText({ images: 3, described: 2, failed: 1, calls: 3, truncated: 2 }),
  ).toMatchObject({ text: "그림 2/3장 설명", tone: "red" });
  expect(imageReportText({ skipped: "AI 모델이 없어요." })).toMatchObject({
    text: "그림 설명 건너뜀",
    tone: "amber",
  });
  expect(imageReportText({ images: 0 }).text).toBe("그림 없음");
});
