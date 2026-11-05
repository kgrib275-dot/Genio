// v0.9 AI 연결: 키 여러 개, 공급자 간 자동 전환, 재정렬 전용 연결
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { AppDetailV2, LlmProvider } from "@/lib/api/types";
import type { ChainLink, TriggerKey } from "@/lib/llmChain";
import type { LlmProbe } from "@/lib/api/workspace";

export interface KeyView {
  id: string;
  label: string;
  masked: string;
  weight: number;
  disabled: boolean;
  primary: boolean;
  position: number;
  calls: number;
  errors: number;
  last_error: string;
  cooldown_seconds: number;
}

/** 서버가 v0.9부터 더 담아 보내는 값(키 목록·돌려쓰기 방식·재정렬 전용 여부) */
export type ProviderV9 = LlmProvider & {
  rerank?: boolean;
  key_strategy?: string;
  keys?: KeyView[];
};

export function asProviderV9(p: LlmProvider): ProviderV9 {
  return p as ProviderV9;
}

// ---------------- 키 ----------------
function useProviderUpdater<V>(ws: string, fn: (v: V) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["llm-providers", ws] }),
  });
}

export function useAddLlmKey(ws: string, providerId: string) {
  return useProviderUpdater(ws, (v: { label: string; api_key: string; weight: number }) =>
    api.post<ProviderV9>(`/workspaces/${ws}/llm-providers/${providerId}/keys`, v),
  );
}

export function usePatchLlmKey(ws: string, providerId: string) {
  return useProviderUpdater(
    ws,
    (v: { id: string; label?: string; weight?: number; disabled?: boolean }) => {
      const { id, ...body } = v;
      return api.patch<ProviderV9>(
        `/workspaces/${ws}/llm-providers/${providerId}/keys/${id}`,
        body,
      );
    },
  );
}

export function useDeleteLlmKey(ws: string, providerId: string) {
  return useProviderUpdater(ws, (keyId: string) =>
    api.del(`/workspaces/${ws}/llm-providers/${providerId}/keys/${keyId}`),
  );
}

export function usePatchLlmProvider(ws: string, providerId: string) {
  return useProviderUpdater(ws, (v: { key_strategy?: string; primary_weight?: number }) =>
    api.patch<ProviderV9>(`/workspaces/${ws}/llm-providers/${providerId}`, v),
  );
}

export function useTestLlmKey(ws: string, providerId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) =>
      api.post<LlmProbe>(`/workspaces/${ws}/llm-providers/${providerId}/keys/${keyId}/test`),
    // 성공하면 쉬던 키가 풀리므로 목록을 다시 읽는다
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["llm-providers", ws] }),
  });
}

// ---------------- 자동 전환 ----------------
export interface FallbackConn {
  id: string;
  label: string;
  provider: string;
  default_model: string;
  key_count: number;
}

export interface FallbackLinkView extends ChainLink {
  label: string;
  provider: string;
  missing: boolean;
}

export interface FallbackView {
  enabled: boolean;
  links: FallbackLinkView[];
  triggers: Record<TriggerKey, boolean>;
  default_triggers: Record<TriggerKey, boolean>;
  connections: FallbackConn[];
}

export interface FallbackSave {
  enabled: boolean;
  links: ChainLink[];
  triggers: Record<TriggerKey, boolean>;
}

export interface FallbackTrail {
  label: string;
  model: string;
  status: "failed" | "skipped" | "answered";
  error: string;
}

export interface FallbackTest {
  ok: boolean;
  message: string;
  hint: string;
  answered_by?: { label: string; provider: string; model: string } | null;
  trail: FallbackTrail[];
  notes: string[];
  ms?: number;
  simulated?: string;
}

export function useFallback(ws: string) {
  return useQuery({
    queryKey: ["llm-fallback", ws],
    queryFn: () => api.get<FallbackView>(`/workspaces/${ws}/llm-fallback`),
    enabled: Boolean(ws),
  });
}

export function useSaveFallback(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: FallbackSave) => api.put<FallbackView>(`/workspaces/${ws}/llm-fallback`, v),
    onSuccess: (data) => qc.setQueryData(["llm-fallback", ws], data),
  });
}

export function useTestFallback(ws: string) {
  return useMutation({
    mutationFn: () => api.post<FallbackTest>(`/workspaces/${ws}/llm-fallback/test`),
  });
}

// ---------------- 앱별 설정(앱 기능 > AI 자동 전환) ----------------
export type FallbackMode = "inherit" | "off" | "custom";

export interface AppFallback {
  mode: FallbackMode;
  links: ChainLink[];
  triggers: Record<TriggerKey, boolean>;
}

export function appFallbackOf(features: unknown): AppFallback {
  const raw = (features as { llm_fallback?: Partial<AppFallback> } | null | undefined)
    ?.llm_fallback;
  const mode: FallbackMode = raw?.mode === "off" || raw?.mode === "custom" ? raw.mode : "inherit";
  return {
    mode,
    links: (raw?.links ?? []).map((l) => ({ provider_id: l.provider_id, model: l.model ?? "" })),
    triggers: {
      outage: true,
      rate_limit: true,
      content_filter: false,
      context_length: false,
      auth: false,
      ...(raw?.triggers ?? {}),
    },
  };
}

export function useSaveAppFallback(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: AppFallback) =>
      api.patch<AppDetailV2>(`/apps/${appId}/features`, { llm_fallback: v }),
    onSuccess: (data) => {
      qc.setQueryData(["app", appId], data);
      void qc.invalidateQueries({ queryKey: ["apps"] });
    },
  });
}

// ---------------- 재정렬 전용 연결 ----------------
export interface RerankConnection {
  id: string;
  label: string;
  provider: string;
  default_model: string;
}

export function useRerankConnections(ws: string) {
  return useQuery({
    queryKey: ["rerank-connections", ws],
    queryFn: () => api.get<RerankConnection[]>(`/workspaces/${ws}/rerank-connections`),
    enabled: Boolean(ws),
  });
}
