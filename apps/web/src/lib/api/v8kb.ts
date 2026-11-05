// v0.8 지식베이스 훅: 가져오기 소스(웹사이트·Notion·공개 Google 문서), 외부 지식베이스,
// 검색 튜닝, 사용 한도(docs/api.md "v0.8 지식 데이터 소스…")
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { KnowledgeBaseV2 } from "@/lib/api/types";

// ---------------- 가져오기 소스 ----------------
export type SourceType = "web" | "notion" | "google";
export type SourceStatus = "new" | "ok" | "partial" | "failed";

export interface SourceSummary {
  added: number;
  updated: number;
  unchanged: number;
  missing: number;
  failed: number;
  notes?: string[];
  failures?: string[];
}

export interface KbSource {
  id: string;
  type: SourceType;
  name: string;
  config: Record<string, unknown>;
  schedule: "none" | "daily";
  created_at: string;
  last_sync_at: string | null;
  last_status: SourceStatus;
  last_summary: SourceSummary | null;
  last_error: string | null;
  running: boolean;
  running_since: string | null;
  progress: { done: number; total: number } | null;
}

export const SOURCE_LABEL: Record<SourceType, string> = {
  web: "웹사이트",
  notion: "Notion",
  google: "Google 문서",
};

export function sourceStatusLabel(s: KbSource): {
  label: string;
  tone: "gray" | "green" | "red" | "amber" | "blue";
} {
  if (s.running) {
    const p = s.progress;
    return {
      label: p && p.total ? `가져오는 중 ${p.done}/${p.total}` : "가져오는 중…",
      tone: "blue",
    };
  }
  switch (s.last_status) {
    case "ok":
      return { label: "최신", tone: "green" };
    case "partial":
      return { label: "일부만 가져옴", tone: "amber" };
    case "failed":
      return { label: "실패", tone: "red" };
    default:
      return { label: "아직 안 가져옴", tone: "gray" };
  }
}

/** 마지막 동기화 결과를 한 줄로("새 3 · 바뀜 1 · 그대로 2") */
export function describeSummary(sum: SourceSummary | null): string {
  if (!sum) return "";
  const parts = [`새 ${sum.added}`, `바뀜 ${sum.updated}`, `그대로 ${sum.unchanged}`];
  if (sum.failed) parts.push(`실패 ${sum.failed}`);
  if (sum.missing) parts.push(`사라짐 ${sum.missing}`);
  return parts.join(" · ");
}

/** 소스의 대상(주소·페이지 수 등)을 짧게 */
export function describeTarget(s: KbSource): string {
  const c = s.config;
  if (s.type === "web") {
    return `${String(c.url ?? "")} · 깊이 ${String(c.depth ?? 1)} · 최대 ${String(c.max_pages ?? 20)}쪽`;
  }
  if (s.type === "notion") {
    return `페이지·데이터베이스 ${(c.targets as unknown[] | undefined)?.length ?? 0}곳`;
  }
  return `문서 ${(c.urls as unknown[] | undefined)?.length ?? 0}개`;
}

export function useKbSources(kbId: string, enabled = true) {
  return useQuery({
    queryKey: ["kb-sources", kbId],
    queryFn: () => api.get<KbSource[]>(`/knowledge-bases/${kbId}/sources`),
    enabled: Boolean(kbId) && enabled,
    // 가져오는 중이면 진행 상황을 계속 읽는다
    refetchInterval: (q) => ((q.state.data ?? []).some((s) => s.running) ? 1500 : false),
  });
}

function useRefreshSources(kbId: string) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["kb-sources", kbId] });
    void qc.invalidateQueries({ queryKey: ["documents", kbId] });
    void qc.invalidateQueries({ queryKey: ["kbs"] });
    void qc.invalidateQueries({ queryKey: ["kb-usage"] });
  };
}

export interface NewSource {
  type: SourceType;
  name?: string;
  config: Record<string, unknown>;
  schedule?: "none" | "daily";
}

export function useAddSource(kbId: string) {
  const refresh = useRefreshSources(kbId);
  return useMutation({
    mutationFn: (v: NewSource) => api.post<KbSource>(`/knowledge-bases/${kbId}/sources`, v),
    onSuccess: refresh,
  });
}

export function usePatchSource(kbId: string) {
  const refresh = useRefreshSources(kbId);
  return useMutation({
    mutationFn: (v: { id: string; name?: string; schedule?: "none" | "daily" }) =>
      api.patch<KbSource>(`/knowledge-bases/${kbId}/sources/${v.id}`, {
        name: v.name,
        schedule: v.schedule,
      }),
    onSuccess: refresh,
  });
}

export function useDeleteSource(kbId: string) {
  const refresh = useRefreshSources(kbId);
  return useMutation({
    mutationFn: (v: { id: string; deleteDocuments: boolean }) =>
      api.del(`/knowledge-bases/${kbId}/sources/${v.id}?delete_documents=${v.deleteDocuments}`),
    onSuccess: refresh,
  });
}

export function useSyncSource(kbId: string) {
  const refresh = useRefreshSources(kbId);
  return useMutation({
    mutationFn: (id: string) => api.post<KbSource>(`/knowledge-bases/${kbId}/sources/${id}/sync`),
    onSuccess: refresh,
  });
}

// ---------------- 외부 지식베이스 ----------------
export interface ExternalConfig {
  endpoint: string;
  knowledge_id: string;
  credential_id: string | null;
}

export interface ExternalTestResult {
  ok: boolean;
  message: string;
  hint: string;
  records: number;
  ms?: number;
  sample?: { title: string; score: number; content: string }[];
}

type KbExt = KnowledgeBaseV2 & {
  kind?: "internal" | "external";
  settings?: KnowledgeBaseV2["settings"] & { external?: ExternalConfig | null };
};

export function isExternalKb(kb: KnowledgeBaseV2 | undefined): boolean {
  return (kb as KbExt | undefined)?.kind === "external";
}

export function externalOf(kb: KnowledgeBaseV2 | undefined): ExternalConfig | null {
  return (kb as KbExt | undefined)?.settings?.external ?? null;
}

export function useCreateExternalKb(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { name: string; project_id?: string; external: ExternalConfig }) =>
      api.post<{ id: string; name: string }>(`/workspaces/${ws}/knowledge-bases`, {
        name: v.name,
        project_id: v.project_id,
        kind: "external",
        external: v.external,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["kbs", ws] }),
  });
}

export function useTestNewExternal(ws: string) {
  return useMutation({
    mutationFn: (v: ExternalConfig & { query?: string }) =>
      api.post<ExternalTestResult>(`/workspaces/${ws}/knowledge-bases/external/test`, v),
  });
}

export function useTestSavedExternal(kbId: string) {
  return useMutation({
    mutationFn: () => api.post<ExternalTestResult>(`/knowledge-bases/${kbId}/external/test`),
  });
}

export function useUpdateExternal(kbId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: ExternalConfig) =>
      api.put<ExternalConfig>(`/knowledge-bases/${kbId}/external`, v),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["kbs"] }),
  });
}

// ---------------- 검색 튜닝 ----------------
export interface TuningQuestion {
  id?: string;
  question: string;
  expect_keyword: string;
  expect_document_id: string;
}

export interface TuningRow {
  method: "vector" | "keyword" | "hybrid";
  top_k: number;
  rerank: boolean;
  hit_rate: number;
  hits: number;
  avg_top_score: number;
  avg_ms: number;
  is_best?: boolean;
  is_current?: boolean;
}

export interface TuningResult {
  at: string;
  questions: number;
  include_rerank: boolean;
  threshold: number;
  rows: TuningRow[];
  best: TuningRow;
  current_row: TuningRow | null;
  suggested_threshold: number | null;
  errors: Record<string, string>;
  truncated: boolean;
}

export interface TuningEstimate {
  questions: number;
  combos: number;
  searches: number;
  embedding_calls: number;
  with_rerank: {
    combos: number;
    searches: number;
    embedding_calls: number;
    rerank_llm_calls: number;
  };
}

export interface TuningState {
  questions: TuningQuestion[];
  last_run: TuningResult | null;
  estimate: TuningEstimate;
  current: { method: TuningRow["method"]; top_k: number; score_threshold: number; rerank: boolean };
  max_questions: number;
}

export const METHOD_NAME: Record<TuningRow["method"], string> = {
  vector: "의미",
  keyword: "낱말",
  hybrid: "혼합",
};

export function rowLabel(r: Pick<TuningRow, "method" | "top_k" | "rerank">): string {
  return `${METHOD_NAME[r.method]} · ${r.top_k}개${r.rerank ? " · 재정렬" : ""}`;
}

/** 적중률을 "67% (2/3)"처럼 */
export function hitText(r: Pick<TuningRow, "hit_rate" | "hits">, total: number): string {
  return `${Math.round(r.hit_rate * 100)}% (${r.hits}/${total})`;
}

/** 지금 설정보다 나아졌는지 알려 주는 한 줄 */
export function improvement(best: TuningRow, current: TuningRow | null): string {
  if (!current) return "";
  const diff = Math.round((best.hit_rate - current.hit_rate) * 100);
  if (diff > 0) return `지금 설정보다 적중률이 ${diff}%p 높아요.`;
  if (diff === 0 && best.avg_top_score > current.avg_top_score)
    return "적중률은 같고 점수가 조금 더 높아요.";
  return "지금 설정이 이미 가장 좋거나 비슷해요.";
}

export function useTuning(kbId: string, enabled = true) {
  return useQuery({
    queryKey: ["kb-tuning", kbId],
    queryFn: () => api.get<TuningState>(`/knowledge-bases/${kbId}/tuning`),
    enabled: Boolean(kbId) && enabled,
  });
}

export function useSaveQuestions(kbId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (questions: TuningQuestion[]) =>
      api.put<{ questions: TuningQuestion[] }>(`/knowledge-bases/${kbId}/tuning/questions`, {
        questions,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["kb-tuning", kbId] }),
  });
}

export function useRunTuning(kbId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { include_rerank: boolean; confirm_rerank: boolean }) =>
      api.post<TuningResult>(`/knowledge-bases/${kbId}/tuning/run`, v),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["kb-tuning", kbId] }),
  });
}

export function useApplyRetrieval(kbId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (r: { method: string; top_k: number; rerank: boolean; score_threshold?: number }) =>
      api.patch(`/knowledge-bases/${kbId}`, { settings: { retrieval: r } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["kbs"] });
      void qc.invalidateQueries({ queryKey: ["kb-tuning", kbId] });
    },
  });
}

// ---------------- 사용 한도 ----------------
export interface KbLimits {
  max_documents: number;
  max_total_mb: number;
  max_writes_per_min: number;
}

export interface KbUsage {
  usage: { documents: number; bytes: number };
  limits: KbLimits;
  can_edit: boolean;
  labels: Record<keyof KbLimits, string>;
}

/** 사용량 / 한도를 0~100으로(한도 0은 제한 없음 → null) */
export function usagePercent(used: number, limit: number): number | null {
  if (!limit) return null;
  return Math.min(100, Math.round((used / limit) * 100));
}

export function useKbUsage(ws: string) {
  return useQuery({
    queryKey: ["kb-usage", ws],
    queryFn: () => api.get<KbUsage>(`/workspaces/${ws}/knowledge/usage`),
    enabled: Boolean(ws),
  });
}

export function useSetKbLimits(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: Partial<KbLimits>) =>
      api.put<{ limits: KbLimits }>(`/workspaces/${ws}/knowledge/limits`, v),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["kb-usage", ws] }),
  });
}
