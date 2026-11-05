// 사람 단계(승인·사람에게 묻기·할 일 맡기기)의 기한·시간 초과 설정 도우미(v0.9)
export const HUMAN_TYPES = ["approval", "ask_person", "assign_task"] as const;

export type OnTimeout = "none" | "reject" | "approve" | "escalate" | "continue" | "branch";

export const ON_TIMEOUT_LABEL: Record<OnTimeout, string> = {
  none: "아무것도 안 함(계속 기다림)",
  reject: "자동 반려(멈춤)",
  approve: "자동 승인",
  escalate: "다른 사람·역할에게 올리기",
  continue: "정해 둔 값으로 계속",
  branch: "'시간 초과' 길로 보내기",
};

export function isHumanType(type: string): boolean {
  return (HUMAN_TYPES as readonly string[]).includes(type);
}

function hours(v: unknown): number {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

/** '시간 초과' 길(timeout 출구)이 생기는 단계인지. */
export function hasTimeoutHandle(type: string, data: Record<string, unknown>): boolean {
  return isHumanType(type) && data.on_timeout === "branch";
}

/** 설정 칸을 숨길지: 올릴 곳은 '올리기'를 골랐을 때만 보인다. */
export function timeoutFieldHidden(
  type: string,
  data: Record<string, unknown>,
  key: string,
): boolean {
  if (!isHumanType(type)) return false;
  if (key === "timeout_escalate_to") return data.on_timeout !== "escalate";
  return false;
}

/** rjsf uiSchema에 숨길 칸을 반영한다(원본은 바꾸지 않는다). */
export function withTimingVisibility(
  ui: Record<string, unknown>,
  type: string,
  data: Record<string, unknown>,
): Record<string, unknown> {
  if (!isHumanType(type)) return ui;
  const out = { ...ui };
  for (const key of ["timeout_escalate_to"]) {
    if (timeoutFieldHidden(type, data, key)) out[key] = { "ui:widget": "hidden" };
  }
  return out;
}

/** 캔버스 카드에 보여 줄 한 줄. 기한을 안 정했으면 빈 글. */
export function describeTiming(type: string, data: Record<string, unknown>): string {
  if (!isHumanType(type)) return "";
  const due = hours(data.due_hours);
  if (!due) return "";
  const mode = (data.on_timeout as OnTimeout | undefined) ?? "none";
  const after = mode === "none" ? "" : ` · 지나면 ${ON_TIMEOUT_LABEL[mode] ?? ""}`;
  const remind = hours(data.remind_before_hours);
  return `기한 ${due}시간${after}${remind ? ` · ${remind}시간 전 알림` : ""}`;
}
