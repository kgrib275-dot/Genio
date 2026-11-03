// v0.5(fork B) API 훅: 연결 테스트·허용할 내부 주소, 외부에서 받기 서명·받은 값, HTTP 시험 호출,
// 모델 카탈로그·임베딩 모델, 사람별 비용·예상 비용, 한도·알림·보관 기간, 마켓 업데이트·미리 보기,
// 문서 켜기·끄기, API 키 권한 범위(docs/api.md v0.5)
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { ProviderPreset, Trigger } from "@/lib/api/types";

// ---------------- 타입 ----------------
export interface CredentialTestResult {
  ok: boolean;
  checked: boolean;
  message: string;
}

export interface TriggerPayload {
  received_at: string;
  accepted: boolean;
  note: string;
  run_id: string | null;
  headers: Record<string, string>;
  body: unknown;
  truncated: boolean;
}

export type TriggerWithSecret = Trigger & { has_secret?: boolean; secret?: string };

export interface HttpPreviewIn {
  method: string;
  url: string;
  headers?: Record<string, string>;
  body?: unknown;
  auth?: HttpAuth | null;
}

export interface HttpAuth {
  type: "none" | "bearer" | "basic" | "header";
  credential_id?: string;
  header_name?: string;
}

export interface HttpPreviewResult {
  status: number;
  headers: Record<string, string>;
  body: unknown;
  truncated: boolean;
  elapsed_ms: number;
}

export interface CatalogModel {
  provider: string;
  model: string;
  label: string;
  context_window: number;
  input_price: number;
  output_price: number;
  tools: boolean;
  vision: boolean;
  embedding: boolean;
  dimensions: number | null;
}

export interface UserUsage {
  user_id: string | null;
  name: string;
  email: string | null;
  runs: number;
  input_tokens: number;
  output_tokens: number;
  cost: number;
}

export interface UsageByUser {
  total_runs: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost: number;
  by_user: UserUsage[];
}

export interface CostEstimate {
  model: string;
  days: number;
  input_tokens: number;
  output_tokens: number;
  current_cost: number;
  estimated_cost: number;
  difference: number;
  price: { input: number; output: number };
}

export interface WorkspaceLimits {
  monthly_budget_usd: number | null;
  cost_alert_usd: number | null;
  alert_on_failure: boolean;
  alert_emails: string[];
  alert_credential_id: string | null;
  retention_days: number | null;
  month_cost: number;
}

export interface InstallationV5 {
  id: string;
  item_key: string;
  item_name: string;
  type: string;
  version: string;
  latest_version: string;
  update_available: boolean;
  status: string;
  installed_at: string;
}

export interface TemplateBlank {
  key: string;
  label: string;
  node_id: string;
  field: string;
  example?: string;
}

export interface TemplatePreview {
  steps: { id: string; type: string; label: string; kind: string; service: string | null }[];
  app_type: "chat" | "workflow" | null;
  blanks: TemplateBlank[];
  requires: string[];
}

export type KeyScope = "chat" | "run" | "logs";

export const KEY_SCOPE_LABELS: Record<KeyScope, string> = {
  chat: "대화",
  run: "흐름 실행",
  logs: "기록 읽기",
};

// ---------------- 연결 정보 ----------------
export function useTestCredential(ws: string) {
  return useMutation({
    mutationFn: (id: string) =>
      api.post<CredentialTestResult>(`/workspaces/${ws}/connectors/credentials/${id}/test`),
  });
}

export function usePrivateHosts(ws: string, enabled = true) {
  return useQuery({
    queryKey: ["private-hosts", ws],
    queryFn: () => api.get<{ hosts: string[] }>(`/workspaces/${ws}/connectors/private-hosts`),
    enabled: Boolean(ws) && enabled,
  });
}

export function useSetPrivateHosts(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (hosts: string[]) =>
      api.put<{ hosts: string[] }>(`/workspaces/${ws}/connectors/private-hosts`, { hosts }),
    onSuccess: (data) => qc.setQueryData(["private-hosts", ws], data),
  });
}

// ---------------- 외부에서 받기(웹훅) ----------------
export function useRotateTriggerSecret(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<TriggerWithSecret>(`/triggers/${id}/secret`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["triggers", appId] }),
  });
}

export function useTriggerPayloads(triggerId: string, enabled = true) {
  return useQuery({
    queryKey: ["trigger-payloads", triggerId],
    queryFn: () => api.get<TriggerPayload[]>(`/triggers/${triggerId}/payloads`),
    enabled: Boolean(triggerId) && enabled,
    refetchInterval: enabled ? 10_000 : false,
  });
}

// ---------------- HTTP 시험 호출 ----------------
export function useHttpPreview(ws: string) {
  return useMutation({
    mutationFn: (v: HttpPreviewIn) =>
      api.post<HttpPreviewResult>(`/workspaces/${ws}/http/preview`, v),
  });
}

// ---------------- 모델·비용 ----------------
/** v0.6: AI 공급자 목록(기본 5종 + OpenAI 호환 preset) */
export function useLlmPresets() {
  return useQuery({
    queryKey: ["llm-presets"],
    queryFn: () => api.get<ProviderPreset[]>("/llm/providers"),
    staleTime: 60 * 60_000,
  });
}

export function useLlmCatalog() {
  return useQuery({
    queryKey: ["llm-catalog"],
    queryFn: () => api.get<CatalogModel[]>("/llm/catalog"),
    staleTime: 10 * 60_000,
  });
}

export function useEmbeddingModels() {
  return useQuery({
    queryKey: ["embedding-models"],
    queryFn: () => api.get<CatalogModel[]>("/llm/embedding-models"),
    staleTime: 10 * 60_000,
  });
}

export function useUsageByUser(ws: string, enabled = true) {
  return useQuery({
    queryKey: ["usage-by-user", ws],
    queryFn: () => api.get<UsageByUser>(`/workspaces/${ws}/usage?group=user`),
    enabled: Boolean(ws) && enabled,
  });
}

export function useCostEstimate(ws: string, model: string, days = 30) {
  return useQuery({
    queryKey: ["cost-estimate", ws, model, days],
    queryFn: () =>
      api.get<CostEstimate>(
        `/workspaces/${ws}/usage/estimate?model=${encodeURIComponent(model)}&days=${days}`,
      ),
    enabled: Boolean(ws && model),
  });
}

export function useLimits(ws: string, enabled = true) {
  return useQuery({
    queryKey: ["limits", ws],
    queryFn: () => api.get<WorkspaceLimits>(`/workspaces/${ws}/limits`),
    enabled: Boolean(ws) && enabled,
  });
}

export function useUpdateLimits(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: Partial<Omit<WorkspaceLimits, "month_cost">>) =>
      api.patch<WorkspaceLimits>(`/workspaces/${ws}/limits`, v),
    onSuccess: (data) => qc.setQueryData(["limits", ws], data),
  });
}

// ---------------- 마켓 ----------------
export function useInstallationsV5(ws: string, enabled = true) {
  return useQuery({
    queryKey: ["installations-v5", ws],
    queryFn: () => api.get<InstallationV5[]>(`/workspaces/${ws}/market/installations`),
    enabled: Boolean(ws) && enabled,
  });
}

export function useUpdateInstallation(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<InstallationV5>(`/workspaces/${ws}/market/installations/${id}/update`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["installations-v5", ws] });
      void qc.invalidateQueries({ queryKey: ["installations", ws] });
      void qc.invalidateQueries({ queryKey: ["market"] });
    },
  });
}

// ---------------- 지식베이스 ----------------
export function useToggleDocument(kbId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; enabled: boolean }) =>
      api.patch<{ id: string; enabled: boolean }>(`/documents/${v.id}`, { enabled: v.enabled }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["documents", kbId] });
      void qc.invalidateQueries({ queryKey: ["kb-documents", kbId] });
    },
  });
}

// ---------------- API 키 권한 범위 ----------------
export interface NewApiKeyV5 {
  id: string;
  name: string;
  prefix: string;
  key: string;
  scopes: KeyScope[];
}

export function useCreateApiKeyScoped(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { name: string; scopes: KeyScope[] }) =>
      api.post<NewApiKeyV5>(`/apps/${appId}/api-keys`, v),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["api-keys", appId] });
      void qc.invalidateQueries({ queryKey: ["app-api-keys", appId] });
    },
  });
}

/** 지식베이스 만들기(임베딩 모델 고정 포함) */
export function useCreateKnowledgeBaseV5(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { name: string; project_id?: string; embedding_model?: string }) =>
      api.post<{ id: string; name: string; embedding_model: string }>(
        `/workspaces/${ws}/knowledge-bases`,
        v,
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["kbs", ws] });
      void qc.invalidateQueries({ queryKey: ["projects", ws] });
    },
  });
}
