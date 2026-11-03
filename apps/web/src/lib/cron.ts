// 예약 실행: 쉬운 선택(매시간·매일·평일·매주) ↔ cron 식, 그리고 쉬운 말 설명.

export type SchedulePreset = "hourly" | "daily" | "weekdays" | "weekly" | "custom";

export interface ScheduleForm {
  preset: SchedulePreset;
  /** 0~59 */
  minute: number;
  /** 0~23 */
  hour: number;
  /** 0(일)~6(토) */
  weekday: number;
  custom: string;
}

export const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

export const DEFAULT_SCHEDULE: ScheduleForm = {
  preset: "daily",
  minute: 0,
  hour: 9,
  weekday: 1,
  custom: "0 9 * * *",
};

export function cronFromForm(f: ScheduleForm): string {
  const m = clamp(f.minute, 0, 59);
  const h = clamp(f.hour, 0, 23);
  switch (f.preset) {
    case "hourly":
      return `${m} * * * *`;
    case "daily":
      return `${m} ${h} * * *`;
    case "weekdays":
      return `${m} ${h} * * 1-5`;
    case "weekly":
      return `${m} ${h} * * ${clamp(f.weekday, 0, 6)}`;
    default:
      return f.custom.trim().replace(/\s+/g, " ");
  }
}

function clamp(n: number, lo: number, hi: number): number {
  return Number.isFinite(n) ? Math.min(hi, Math.max(lo, Math.round(n))) : lo;
}

const NUM = /^\d{1,2}$/;

/** cron 식을 쉬운 선택으로 되돌린다. 맞는 것이 없으면 '직접'. */
export function formFromCron(cron: string): ScheduleForm {
  const c = cron.trim().replace(/\s+/g, " ");
  const parts = c.split(" ");
  const base = { ...DEFAULT_SCHEDULE, custom: c };
  if (parts.length !== 5) return { ...base, preset: "custom" };
  const [mi, ho, dom, mon, dow] = parts as [string, string, string, string, string];
  if (!NUM.test(mi) || dom !== "*" || mon !== "*") return { ...base, preset: "custom" };
  const minute = Number(mi);
  if (ho === "*" && dow === "*") return { ...base, preset: "hourly", minute };
  if (!NUM.test(ho)) return { ...base, preset: "custom" };
  const hour = Number(ho);
  if (dow === "*") return { ...base, preset: "daily", minute, hour };
  if (dow === "1-5") return { ...base, preset: "weekdays", minute, hour };
  if (/^[0-7]$/.test(dow))
    return { ...base, preset: "weekly", minute, hour, weekday: Number(dow) % 7 };
  return { ...base, preset: "custom" };
}

function timeText(hour: number, minute: number): string {
  const ampm = hour < 12 ? "오전" : "오후";
  const h12 = hour % 12 === 0 ? 12 : hour % 12;
  return `${ampm} ${h12}:${String(minute).padStart(2, "0")}`;
}

/** cron 식을 쉬운 말로. 예: "평일(월~금) 오전 9:00" */
export function describeCron(cron: string): string {
  const f = formFromCron(cron);
  switch (f.preset) {
    case "hourly":
      return f.minute === 0 ? "매시간 정각" : `매시간 ${f.minute}분`;
    case "daily":
      return `매일 ${timeText(f.hour, f.minute)}`;
    case "weekdays":
      return `평일(월~금) ${timeText(f.hour, f.minute)}`;
    case "weekly":
      return `매주 ${WEEKDAYS[f.weekday] ?? "?"}요일 ${timeText(f.hour, f.minute)}`;
    default:
      return `직접 정한 일정 (${cron})`;
  }
}

/** 화면에서 미리 걸러 낼 수 있는 cron 형식 문제(정확한 검사는 서버가 한다). */
export function cronProblem(cron: string): string | null {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5 || parts.some((p) => !p)) return "칸이 5개여야 해요(분 시 일 월 요일).";
  if (parts.some((p) => !/^[\d*/,\-A-Za-z]+$/.test(p))) return "쓸 수 없는 글자가 있어요.";
  return null;
}
