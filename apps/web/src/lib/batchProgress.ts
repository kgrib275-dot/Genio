// 일괄 실행 진행 표시를 계산한다(화면에서 쓰는 순수 함수).
import type { BatchRowStatus } from "@/lib/api/batches";

export interface ProgressInfo {
  /** 0~100: 끝난 줄(성공·실패·취소·승인 대기) 비율 */
  percent: number;
  settled: number;
  total: number;
  summary: string;
}

const NAMES: [BatchRowStatus, string][] = [
  ["succeeded", "성공"],
  ["failed", "실패"],
  ["cancelled", "취소"],
  ["waiting_approval", "승인 대기"],
  ["running", "실행 중"],
  ["queued", "대기"],
];

export function progressOf(
  counts: Partial<Record<BatchRowStatus, number>>,
  total: number,
): ProgressInfo {
  const settled =
    (counts.succeeded ?? 0) +
    (counts.failed ?? 0) +
    (counts.cancelled ?? 0) +
    (counts.waiting_approval ?? 0);
  const percent = total > 0 ? Math.min(100, Math.round((settled / total) * 100)) : 0;
  const parts = NAMES.filter(([k]) => (counts[k] ?? 0) > 0).map(([k, n]) => `${n} ${counts[k]}`);
  return { percent, settled, total, summary: parts.join(" · ") };
}
