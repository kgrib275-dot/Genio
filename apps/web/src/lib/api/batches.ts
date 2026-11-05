// v0.8 일괄 실행: 양식 내려받기 → 표 올려 미리 보기 → 실행 → 진행 보기 → 결과 표 내려받기.
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, rawRequest, toApiError } from "@/lib/api/client";

/** 앱 안(제작자 이상) 또는 공유 링크에서 쓴다. 공유 링크는 한 번에 50건까지. */
export type BatchSource = { kind: "app"; appId: string } | { kind: "public"; token: string };

export interface BatchField {
  key: string;
  label: string;
  type: string;
  required: boolean;
}

export interface RowError {
  message: string;
  hint: string;
}

export interface PreviewRow {
  /** 파일에서의 줄 번호(머리글이 1줄) */
  row: number;
  values: Record<string, unknown>;
  errors: RowError[];
}

export interface BatchPreview {
  fields: BatchField[];
  max_rows: number;
  columns: { header: string; field: string | null }[];
  unmatched: string[];
  rows: PreviewRow[];
  total: number;
  ok_count: number;
  error_count: number;
}

export type BatchRowStatus =
  "queued" | "running" | "succeeded" | "failed" | "cancelled" | "waiting_approval";

export interface BatchStatus {
  batch_id: string;
  total: number;
  counts: Record<BatchRowStatus, number>;
  settled: number;
  done: boolean;
  cancelled: boolean;
  created_at: string;
  rows: {
    row: number;
    status: BatchRowStatus;
    input: Record<string, unknown>;
    text: string;
    error?: RowError;
    run_id?: string;
    /** v0.9: 이 줄이 만든 파일(파일을 만드는 흐름일 때) */
    files?: { id: string; filename: string; kind: string; url?: string }[];
  }[];
}

export const BATCH_STATUS_LABEL: Record<BatchRowStatus, string> = {
  queued: "대기",
  running: "실행 중",
  succeeded: "성공",
  failed: "실패",
  cancelled: "취소",
  waiting_approval: "승인 대기",
};

export function batchBase(src: BatchSource): string {
  return src.kind === "app" ? `/apps/${src.appId}/batches` : `/public/apps/${src.token}/batches`;
}

export function usePreviewBatch(src: BatchSource) {
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api.upload<BatchPreview>(`${batchBase(src)}/preview`, form);
    },
  });
}

export function useCreateBatch(src: BatchSource) {
  return useMutation({
    mutationFn: (v: {
      rows: { row: number; values: Record<string, unknown> }[];
      skipInvalid: boolean;
    }) =>
      api.post<{ batch_id: string; total: number }>(batchBase(src), {
        rows: v.rows,
        skip_invalid: v.skipInvalid,
      }),
  });
}

export function useBatchStatus(src: BatchSource, batchId: string | null) {
  return useQuery({
    queryKey: ["batch", batchBase(src), batchId],
    queryFn: () => api.get<BatchStatus>(`${batchBase(src)}/${batchId}`),
    enabled: Boolean(batchId),
    // 끝날 때까지 1초마다 진행 상황을 다시 읽는다
    refetchInterval: (q) => (q.state.data?.done ? false : 1000),
  });
}

export function useCancelBatch(src: BatchSource) {
  return useMutation({
    mutationFn: (batchId: string) =>
      api.post<{ cancelled: number }>(`${batchBase(src)}/${batchId}/cancel`),
  });
}

/** 양식·결과 CSV를 내려받는다(로그인 헤더가 필요해서 링크 대신 받아서 저장). */
export async function downloadBatchFile(
  src: BatchSource,
  kind: "template" | "results",
  batchId?: string,
): Promise<void> {
  const path =
    kind === "template"
      ? `${batchBase(src)}/template.csv`
      : `${batchBase(src)}/${batchId}/results.csv`;
  const res = await rawRequest(path);
  if (!res.ok) throw await toApiError(res);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = kind === "template" ? "일괄실행-양식.csv" : "일괄실행-결과.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
