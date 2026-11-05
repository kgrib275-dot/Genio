// 실행 목록·단계 목록이 함께 쓰는 이름표와 필터
import type { Run } from "@/lib/api/types";
import type { FilterDef } from "@/lib/useListControls";

export const TRIGGER: Record<string, string> = {
  test: "테스트",
  chat: "챗",
  api: "API",
  schedule: "예약",
  batch: "일괄",
};

/** 실행·단계 상태 이름(필터 선택지용) */
export const RUN_STATUS: Record<string, string> = {
  queued: "대기",
  running: "실행 중",
  succeeded: "성공",
  failed: "실패",
  waiting_approval: "승인 대기",
  skipped: "건너뜀",
};

const toOptions = (m: Record<string, string>) =>
  Object.entries(m).map(([value, label]) => ({ value, label }));

export const RUN_FILTERS: FilterDef<Run>[] = [
  {
    id: "status",
    label: "상태",
    options: toOptions(RUN_STATUS).filter((o) => o.value !== "skipped"),
    match: (r, v) => r.status === v,
  },
  {
    id: "trigger",
    label: "방식",
    options: toOptions(TRIGGER),
    match: (r, v) => r.trigger === v,
  },
];

export function runSearchText(r: Run): string {
  return [
    r.id,
    r.app_name ?? "",
    r.error ?? "",
    r.output?.text ?? "",
    RUN_STATUS[r.status] ?? r.status,
  ].join(" ");
}
