import {
  cronFromForm,
  cronProblem,
  DEFAULT_SCHEDULE,
  describeCron,
  formFromCron,
} from "@/lib/cron";

describe("예약 일정", () => {
  it("쉬운 선택을 cron 식으로", () => {
    const f = { ...DEFAULT_SCHEDULE, minute: 30, hour: 14, weekday: 3 };
    expect(cronFromForm({ ...f, preset: "hourly" })).toBe("30 * * * *");
    expect(cronFromForm({ ...f, preset: "daily" })).toBe("30 14 * * *");
    expect(cronFromForm({ ...f, preset: "weekdays" })).toBe("30 14 * * 1-5");
    expect(cronFromForm({ ...f, preset: "weekly" })).toBe("30 14 * * 3");
    expect(cronFromForm({ ...f, preset: "custom", custom: " */5  * * * * " })).toBe("*/5 * * * *");
  });

  it("cron 식을 다시 쉬운 선택으로(왕복)", () => {
    for (const c of ["15 * * * *", "0 9 * * *", "0 9 * * 1-5", "45 18 * * 0"])
      expect(cronFromForm(formFromCron(c))).toBe(c);
    expect(formFromCron("*/5 * * * *").preset).toBe("custom");
    expect(formFromCron("0 9 1 * *").preset).toBe("custom");
  });

  it("쉬운 말 설명", () => {
    expect(describeCron("0 * * * *")).toBe("매시간 정각");
    expect(describeCron("0 9 * * 1-5")).toBe("평일(월~금) 오전 9:00");
    expect(describeCron("5 13 * * 1")).toBe("매주 월요일 오후 1:05");
    expect(describeCron("0 0 * * *")).toBe("매일 오전 12:00");
    expect(describeCron("*/10 * * * *")).toContain("직접 정한 일정");
  });

  it("형식 문제 미리 알려 주기", () => {
    expect(cronProblem("0 9 * * *")).toBeNull();
    expect(cronProblem("0 9 * *")).toContain("5개");
    expect(cronProblem("0 9 * * ;")).toContain("글자");
  });
});
