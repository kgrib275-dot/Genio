import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type {
  AuditLog,
  Invitation,
  LlmProvider,
  Member,
  NodeType,
  ProviderKind,
  Role,
  Run,
  Usage,
} from "@/lib/api/types";

export function useMembers(ws: string) {
  return useQuery({
    queryKey: ["members", ws],
    queryFn: () => api.get<Member[]>(`/workspaces/${ws}/members`),
    enabled: Boolean(ws),
  });
}

export function useUpdateMemberRole(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; role: Role }) =>
      api.patch<Member>(`/workspaces/${ws}/members/${v.id}`, { role: v.role }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["members", ws] }),
  });
}

export function useInvitations(ws: string, enabled = true) {
  return useQuery({
    queryKey: ["invitations", ws],
    queryFn: () => api.get<Invitation[]>(`/workspaces/${ws}/invitations`),
    enabled: Boolean(ws) && enabled,
  });
}

export function useInvite(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { email: string; role: Role }) =>
      api.post<Invitation>(`/workspaces/${ws}/invitations`, v),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["invitations", ws] }),
  });
}

export function useLlmProviders(ws: string, enabled = true) {
  return useQuery({
    queryKey: ["llm-providers", ws],
    queryFn: () => api.get<LlmProvider[]>(`/workspaces/${ws}/llm-providers`),
    enabled: Boolean(ws) && enabled,
  });
}

export interface NewLlmProvider {
  provider: ProviderKind;
  label: string;
  api_key: string;
  base_url?: string;
  default_model: string;
  is_default: boolean;
}

export function useCreateLlmProvider(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: NewLlmProvider) => api.post<LlmProvider>(`/workspaces/${ws}/llm-providers`, v),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["llm-providers", ws] }),
  });
}

export function useDeleteLlmProvider(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/workspaces/${ws}/llm-providers/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["llm-providers", ws] }),
  });
}

export function useNodeTypes(ws: string) {
  return useQuery({
    queryKey: ["nodes", ws],
    queryFn: () => api.get<NodeType[]>(`/workspaces/${ws}/nodes`),
    enabled: Boolean(ws),
    staleTime: 60_000,
  });
}

export interface RunFilter {
  app?: string;
  status?: string;
  from?: string;
  to?: string;
}

function qs(params: Record<string, string | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) sp.set(k, v);
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export function useWorkspaceRuns(ws: string, filter: RunFilter = {}, enabled = true) {
  return useQuery({
    queryKey: ["ws-runs", ws, filter],
    queryFn: () => api.get<Run[]>(`/workspaces/${ws}/runs${qs({ limit: "1000", ...filter })}`),
    enabled: Boolean(ws) && enabled,
  });
}

export function useUsage(ws: string, range: { from?: string; to?: string } = {}) {
  return useQuery({
    queryKey: ["usage", ws, range],
    queryFn: () => api.get<Usage>(`/workspaces/${ws}/usage${qs(range)}`),
    enabled: Boolean(ws),
  });
}

export function useAuditLogs(ws: string, enabled = true) {
  return useQuery({
    queryKey: ["audit-logs", ws],
    queryFn: () => api.get<AuditLog[]>(`/workspaces/${ws}/audit-logs?limit=1000`),
    enabled: Boolean(ws) && enabled,
  });
}

// v0.6: AI 연결 테스트(키로 공급자 모델 목록 불러오기)
export interface LlmProbe {
  ok: boolean;
  message: string;
  hint: string;
  models: { model: string; label: string }[];
  ms?: number;
}

export function useTestNewLlm(ws: string) {
  return useMutation({
    mutationFn: (v: {
      provider: string;
      api_key: string;
      base_url?: string | null;
      model?: string;
    }) => api.post<LlmProbe>(`/workspaces/${ws}/llm-providers/test`, v),
  });
}

export function useTestSavedLlm(ws: string) {
  return useMutation({
    mutationFn: (id: string) => api.post<LlmProbe>(`/workspaces/${ws}/llm-providers/${id}/test`),
  });
}
