// v0.9 서비스 이벤트로 시작하기(Slack·GitHub·Shopify·Telegram·Jira·Typeform) API 훅
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { Run, Trigger } from "@/lib/api/types";
import type { TriggerWithSecret } from "@/lib/api/v5b";

export interface ServicePreset {
  key: string;
  name: string;
  /** generated: 제니오가 만들어 한 번 보여 주는 비밀값을 서비스에 붙여 넣는다 / provider: 서비스가 정해 준 값을 제니오에 붙여 넣는다 */
  key_origin: "generated" | "provider";
  key_label: string;
  events: { id: string; label: string }[];
  instructions: string[];
  sample: { headers: Record<string, string>; body: unknown };
}

export interface ServiceConfig {
  service: string;
  events: string[];
  mapping: Record<string, string>;
  include_bot: boolean;
  version?: number | null;
}

export function serviceConfigOf(t: Pick<Trigger, "config">): ServiceConfig {
  const c = (t.config ?? {}) as Partial<ServiceConfig>;
  return {
    service: c.service ?? "",
    events: c.events ?? [],
    mapping: c.mapping ?? {},
    include_bot: Boolean(c.include_bot),
    version: c.version ?? null,
  };
}

export function useServicePresets(appId: string, enabled = true) {
  return useQuery({
    queryKey: ["service-presets", appId],
    queryFn: () => api.get<ServicePreset[]>(`/apps/${appId}/service-presets`),
    enabled: Boolean(appId) && enabled,
    staleTime: 5 * 60_000,
  });
}

function useInvalidate(appId: string) {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: ["triggers", appId] });
}

export function useCreateServiceTrigger(appId: string) {
  const done = useInvalidate(appId);
  return useMutation({
    mutationFn: (v: { name?: string; config: Partial<ServiceConfig>; secret?: string }) =>
      api.post<TriggerWithSecret>(`/apps/${appId}/triggers`, { kind: "service", ...v }),
    onSuccess: done,
  });
}

export function useUpdateServiceTrigger(appId: string) {
  const done = useInvalidate(appId);
  return useMutation({
    mutationFn: (v: {
      id: string;
      name?: string;
      enabled?: boolean;
      config?: Partial<ServiceConfig>;
    }) => {
      const { id, ...body } = v;
      return api.patch<Trigger>(`/triggers/${id}`, body);
    },
    onSuccess: done,
  });
}

/** 서비스가 정해 준 비밀값(Slack·Shopify)을 바꿔 넣는다. 제니오가 만드는 서비스는 비밀값 새로 만들기를 쓴다. */
export function useSetProviderSecret(appId: string) {
  const done = useInvalidate(appId);
  return useMutation({
    mutationFn: (v: { id: string; secret: string }) =>
      api.post<TriggerWithSecret>(`/triggers/${v.id}/secret`, { secret: v.secret }),
    onSuccess: done,
  });
}

export function useTestSample(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<{ run: Run; input: Record<string, unknown> }>(`/triggers/${id}/test-sample`),
    onSuccess: (_r, id) => {
      void qc.invalidateQueries({ queryKey: ["triggers", appId] });
      void qc.invalidateQueries({ queryKey: ["trigger-payloads", id] });
      void qc.invalidateQueries({ queryKey: ["app-runs", appId] });
    },
  });
}
