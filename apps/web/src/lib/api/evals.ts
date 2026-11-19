// 후속(O1): 평가 세트 — 질문·조건을 모아 한 번에 돌리고 채점한다
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface EvalCase {
  id: string;
  name: string;
  input: Record<string, unknown>;
  contains: string[];
  not_contains: string[];
  max_seconds: number | null;
  json_valid: boolean;
  /** AI 심판 기준(비우면 쓰지 않는다) */
  judge?: string;
}

export interface EvalCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface EvalResult {
  run_id: string;
  case_id: string;
  name: string;
  status: string;
  finished: boolean;
  passed: boolean | null;
  checks: EvalCheck[];
  seconds: number | null;
  answer: string;
  cost: number;
}

export interface EvalSummary {
  batch: string;
  total: number;
  finished: number;
  passed: number;
  pass_rate: number | null;
  avg_seconds: number | null;
  cost: number;
  running: boolean;
  created_at: string | null;
  dropped?: boolean;
  previous_pass_rate?: number | null;
}

export interface EvalReport extends EvalSummary {
  results: EvalResult[];
}

export function useEvalCases(appId: string) {
  return useQuery({
    queryKey: ["eval-cases", appId],
    queryFn: () => api.get<{ cases: EvalCase[]; max_cases: number }>(`/apps/${appId}/evals/cases`),
    enabled: Boolean(appId),
  });
}

export function useSaveEvalCases(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (cases: EvalCase[]) =>
      api.put<{ cases: EvalCase[]; max_cases: number }>(`/apps/${appId}/evals/cases`, { cases }),
    onSuccess: (data) => qc.setQueryData(["eval-cases", appId], data),
  });
}

export function useEvalHistory(appId: string) {
  return useQuery({
    queryKey: ["eval-history", appId],
    queryFn: () => api.get<{ batches: EvalSummary[] }>(`/apps/${appId}/evals`),
    enabled: Boolean(appId),
    // 돌아가는 평가가 있으면 3초마다 새로 본다
    refetchInterval: (q) => (q.state.data?.batches.some((b) => b.running) ? 3000 : false),
  });
}

export function useEvalReport(appId: string, batch: string | null) {
  return useQuery({
    queryKey: ["eval-report", appId, batch],
    queryFn: () => api.get<EvalReport>(`/apps/${appId}/evals/${batch}`),
    enabled: Boolean(appId && batch),
    refetchInterval: (q) => (q.state.data?.running ? 3000 : false),
  });
}

export function useRunEval(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ batch: string; total: number }>(`/apps/${appId}/evals`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["eval-history", appId] }),
  });
}

/** 통과율을 '67%'로 */
export function formatRate(rate: number | null | undefined): string {
  return rate == null ? "-" : `${Math.round(rate * 100)}%`;
}

/** 줄마다·쉼표로 적은 말을 목록으로 */
export function splitTerms(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((t) => t.trim())
    .filter(Boolean);
}

export interface EvalGate {
  enabled: boolean;
  min_pass_rate: number;
}

export function useEvalGate(appId: string) {
  return useQuery({
    queryKey: ["eval-gate", appId],
    queryFn: () => api.get<EvalGate>(`/apps/${appId}/evals/gate`),
    enabled: Boolean(appId),
  });
}

export function useSaveEvalGate(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (g: EvalGate) => api.put<EvalGate>(`/apps/${appId}/evals/gate`, g),
    onSuccess: (data) => qc.setQueryData(["eval-gate", appId], data),
  });
}
