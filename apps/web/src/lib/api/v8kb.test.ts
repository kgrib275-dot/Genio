import {
  describeSummary,
  describeTarget,
  hitText,
  improvement,
  rowLabel,
  sourceStatusLabel,
  usagePercent,
  type KbSource,
  type TuningRow,
} from "@/lib/api/v8kb";

const base: KbSource = {
  id: "s1",
  type: "web",
  name: "문서 사이트",
  config: { url: "https://docs.example.com/", depth: 2, max_pages: 30 },
  schedule: "none",
  created_at: "2026-11-05T00:00:00Z",
  last_sync_at: null,
  last_status: "new",
  last_summary: null,
  last_error: null,
  running: false,
  running_since: null,
  progress: null,
};

test("소스 상태 문구: 진행 중·최신·일부·실패", () => {
  expect(sourceStatusLabel(base).label).toBe("아직 안 가져옴");
  expect(sourceStatusLabel({ ...base, running: true, progress: { done: 3, total: 20 } })).toEqual({
    label: "가져오는 중 3/20",
    tone: "blue",
  });
  expect(sourceStatusLabel({ ...base, running: true }).label).toBe("가져오는 중…");
  expect(sourceStatusLabel({ ...base, last_status: "ok" }).tone).toBe("green");
  expect(sourceStatusLabel({ ...base, last_status: "partial" }).label).toBe("일부만 가져옴");
  expect(sourceStatusLabel({ ...base, last_status: "failed" }).tone).toBe("red");
});

test("동기화 결과 한 줄과 대상 설명", () => {
  expect(describeSummary(null)).toBe("");
  expect(describeSummary({ added: 3, updated: 1, unchanged: 2, missing: 0, failed: 0 })).toBe(
    "새 3 · 바뀜 1 · 그대로 2",
  );
  expect(describeSummary({ added: 0, updated: 0, unchanged: 5, missing: 1, failed: 2 })).toBe(
    "새 0 · 바뀜 0 · 그대로 5 · 실패 2 · 사라짐 1",
  );
  expect(describeTarget(base)).toBe("https://docs.example.com/ · 깊이 2 · 최대 30쪽");
  expect(describeTarget({ ...base, type: "notion", config: { targets: ["a", "b"] } })).toBe(
    "페이지·데이터베이스 2곳",
  );
  expect(describeTarget({ ...base, type: "google", config: { urls: ["x"] } })).toBe("문서 1개");
});

const row = (p: Partial<TuningRow>): TuningRow => ({
  method: "hybrid",
  top_k: 5,
  rerank: false,
  hit_rate: 0.5,
  hits: 1,
  avg_top_score: 0.5,
  avg_ms: 10,
  ...p,
});

test("튜닝 표 문구: 이름·적중률·개선 안내", () => {
  expect(rowLabel(row({}))).toBe("혼합 · 5개");
  expect(rowLabel(row({ method: "vector", top_k: 3, rerank: true }))).toBe("의미 · 3개 · 재정렬");
  expect(hitText(row({ hit_rate: 0.6667, hits: 2 }), 3)).toBe("67% (2/3)");
  expect(improvement(row({ hit_rate: 1 }), row({ hit_rate: 0.5 }))).toBe(
    "지금 설정보다 적중률이 50%p 높아요.",
  );
  expect(improvement(row({ hit_rate: 0.5, avg_top_score: 0.9 }), row({ hit_rate: 0.5 }))).toBe(
    "적중률은 같고 점수가 조금 더 높아요.",
  );
  expect(improvement(row({ hit_rate: 0.4 }), row({ hit_rate: 0.5 }))).toBe(
    "지금 설정이 이미 가장 좋거나 비슷해요.",
  );
  expect(improvement(row({}), null)).toBe("");
});

test("사용량 비율: 한도 0은 제한 없음", () => {
  expect(usagePercent(50, 200)).toBe(25);
  expect(usagePercent(500, 200)).toBe(100);
  expect(usagePercent(5, 0)).toBeNull();
});
