import {
  describeTiming,
  hasTimeoutHandle,
  timeoutFieldHidden,
  withTimingVisibility,
} from "@/components/canvas/humanTiming";

test("'시간 초과' 길은 사람 단계가 branch를 골랐을 때만 생긴다", () => {
  expect(hasTimeoutHandle("approval", { on_timeout: "branch" })).toBe(true);
  expect(hasTimeoutHandle("ask_person", { on_timeout: "branch" })).toBe(true);
  expect(hasTimeoutHandle("assign_task", { on_timeout: "reject" })).toBe(false);
  expect(hasTimeoutHandle("llm", { on_timeout: "branch" })).toBe(false);
});

test("올릴 곳 칸은 '올리기'를 골랐을 때만 보인다", () => {
  expect(timeoutFieldHidden("approval", { on_timeout: "none" }, "timeout_escalate_to")).toBe(true);
  expect(timeoutFieldHidden("approval", { on_timeout: "escalate" }, "timeout_escalate_to")).toBe(
    false,
  );
  expect(timeoutFieldHidden("llm", {}, "timeout_escalate_to")).toBe(false);
  const ui = withTimingVisibility({ message: { "ui:widget": "textarea" } }, "ask_person", {});
  expect(ui.timeout_escalate_to).toEqual({ "ui:widget": "hidden" });
  expect(ui.message).toEqual({ "ui:widget": "textarea" });
  const shown = withTimingVisibility({}, "ask_person", { on_timeout: "escalate" });
  expect(shown.timeout_escalate_to).toBeUndefined();
});

test("카드에 보이는 기한 문장", () => {
  expect(describeTiming("approval", {})).toBe("");
  expect(describeTiming("approval", { due_hours: 24 })).toBe("기한 24시간");
  expect(describeTiming("approval", { due_hours: 24, on_timeout: "reject" })).toBe(
    "기한 24시간 · 지나면 자동 반려(멈춤)",
  );
  expect(
    describeTiming("assign_task", { due_hours: 8, on_timeout: "escalate", remind_before_hours: 2 }),
  ).toBe("기한 8시간 · 지나면 다른 사람·역할에게 올리기 · 2시간 전 알림");
  expect(describeTiming("llm", { due_hours: 5 })).toBe("");
});
