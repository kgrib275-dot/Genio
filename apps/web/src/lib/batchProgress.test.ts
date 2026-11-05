import { progressOf } from "@/lib/batchProgress";

test("끝난 줄 비율과 요약 문장을 계산한다", () => {
  const p = progressOf({ succeeded: 6, failed: 1, queued: 3, running: 2 }, 12);
  expect(p.settled).toBe(7);
  expect(p.percent).toBe(58);
  expect(p.summary).toBe("성공 6 · 실패 1 · 실행 중 2 · 대기 3");
});

test("줄이 없으면 0%, 모두 끝나면 100%", () => {
  expect(progressOf({}, 0).percent).toBe(0);
  expect(progressOf({ succeeded: 4, cancelled: 1 }, 5).percent).toBe(100);
});
