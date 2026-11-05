// v0.9 외부 추적: 여러 서비스(Langfuse·LangSmith·OpenTelemetry·Phoenix·Arize·Opik·Weave) 설정·시험
// (docs/api.md v0.9 관측 도구 확대). 설정은 소유자·관리자만 읽고 쓴다.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export type TraceFieldType = "text" | "url" | "secret" | "headers";

export interface TraceField {
  key: string;
  label: string;
  type: TraceFieldType;
  required: boolean;
  default: string;
  hint: string;
  placeholder: string;
}

export interface TraceKind {
  kind: string;
  label: string;
  /** 문서로 확인하지 못한 부분이 있는 서비스 */
  experimental: boolean;
  description: string;
  fields: TraceField[];
}

export interface TraceLast {
  at: string;
  ok: boolean;
  message: string;
}

export interface TraceProvider {
  id: string;
  kind: string;
  kind_label: string;
  experimental: boolean;
  name: string;
  enabled: boolean;
  sample_rate: number;
  only_failed: boolean;
  fields: Record<string, string>;
  secrets: Record<string, { has: boolean; masked: string }>;
  headers: { name: string; masked: string }[];
  ready: boolean;
  last: TraceLast | null;
}

export interface TraceConfig {
  include_content: boolean;
  kinds: TraceKind[];
  providers: TraceProvider[];
}

/** 저장할 때 보내는 서비스 한 개(비밀 칸은 새로 넣었을 때만 값이 있다) */
export interface TraceProviderIn {
  id?: string;
  kind: string;
  name: string;
  enabled: boolean;
  sample_rate: number;
  only_failed: boolean;
  fields: Record<string, string>;
  secrets: Record<string, string>;
  clear_secrets: string[];
  headers: { name: string; value: string }[];
}

export interface TraceTestResult {
  ok: boolean;
  message: string;
}

export function useTraceConfig(ws: string) {
  return useQuery({
    queryKey: ["tracing", ws],
    queryFn: () => api.get<TraceConfig>(`/workspaces/${ws}/tracing`),
    enabled: Boolean(ws),
  });
}

export function useSaveTraceConfig(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { include_content: boolean; providers: TraceProviderIn[] }) =>
      api.put<TraceConfig>(`/workspaces/${ws}/tracing`, body),
    onSuccess: (data) => qc.setQueryData(["tracing", ws], data),
  });
}

export function useTestTrace(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (target: string) =>
      api.post<TraceTestResult>(`/workspaces/${ws}/tracing/test`, { target }),
    // 시험 결과(마지막 전송)가 서버에 남으므로 다시 읽어 상태 표시를 새로 한다
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["tracing", ws] }),
  });
}
