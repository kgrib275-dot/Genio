// 지식베이스·연결 정보·마켓·공개 앱 훅
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiFetch } from "@/lib/api/client";
import { streamSSE, type SSEEvent } from "@/lib/api/sse";
import type {
  ConnectorCredential,
  ConnectorDefinition,
  Installation,
  KbDocument,
  KnowledgeBase,
  MarketItem,
  MarketItemDetail,
  PromptPack,
  PublicApp,
  SearchHit,
  Template,
} from "@/lib/api/types";

// ---------- 지식베이스 ----------
export function useKnowledgeBases(ws: string) {
  return useQuery({
    queryKey: ["kbs", ws],
    queryFn: () => api.get<KnowledgeBase[]>(`/workspaces/${ws}/knowledge-bases`),
    enabled: Boolean(ws),
  });
}

export function useCreateKnowledgeBase(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { name: string; chunk_size?: number }) =>
      api.post<KnowledgeBase>(`/workspaces/${ws}/knowledge-bases`, v),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["kbs", ws] }),
  });
}

export function useDeleteKnowledgeBase(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/knowledge-bases/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["kbs", ws] }),
  });
}

export function useDocuments(kbId: string) {
  return useQuery({
    queryKey: ["documents", kbId],
    queryFn: () => api.get<KbDocument[]>(`/knowledge-bases/${kbId}/documents`),
    enabled: Boolean(kbId),
    refetchInterval: (q) =>
      (q.state.data ?? []).some((d) => d.status === "uploaded" || d.status === "processing")
        ? 2000
        : false,
  });
}

export function useUploadDocument(kbId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api.upload<KbDocument>(`/knowledge-bases/${kbId}/documents`, form);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["documents", kbId] });
      void qc.invalidateQueries({ queryKey: ["kbs"] });
    },
  });
}

export function useDeleteDocument(kbId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/documents/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["documents", kbId] }),
  });
}

export function searchKnowledgeBase(kbId: string, query: string, topK = 5): Promise<SearchHit[]> {
  return api.post<SearchHit[]>(`/knowledge-bases/${kbId}/search`, { query, top_k: topK });
}

// ---------- 연결 정보 ----------
export function useConnectorDefinitions(ws: string) {
  return useQuery({
    queryKey: ["connector-defs", ws],
    queryFn: () => api.get<ConnectorDefinition[]>(`/workspaces/${ws}/connectors/definitions`),
    enabled: Boolean(ws),
  });
}

export function useCredentials(ws: string, enabled = true) {
  return useQuery({
    queryKey: ["credentials", ws],
    queryFn: () => api.get<ConnectorCredential[]>(`/workspaces/${ws}/connectors/credentials`),
    enabled: Boolean(ws) && enabled,
  });
}

export function useCreateCredential(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { connector_key: string; name: string; secrets: Record<string, string> }) =>
      api.post<ConnectorCredential>(`/workspaces/${ws}/connectors/credentials`, v),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["credentials", ws] }),
  });
}

export function useDeleteCredential(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/workspaces/${ws}/connectors/credentials/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["credentials", ws] }),
  });
}

// ---------- 마켓 ----------
export function useMarketItems(ws: string, filter: { type?: string; q?: string }) {
  const sp = new URLSearchParams();
  if (filter.type) sp.set("type", filter.type);
  if (filter.q) sp.set("q", filter.q);
  if (ws) sp.set("workspace_id", ws);
  return useQuery({
    queryKey: ["market", ws, filter],
    queryFn: () => api.get<MarketItem[]>(`/market/items?${sp.toString()}`),
  });
}

export function useMarketItem(key: string, ws: string) {
  return useQuery({
    queryKey: ["market-item", key, ws],
    queryFn: () =>
      api.get<MarketItemDetail>(
        `/market/items/${key}${ws ? `?workspace_id=${encodeURIComponent(ws)}` : ""}`,
      ),
    enabled: Boolean(key),
  });
}

function invalidateMarket(qc: ReturnType<typeof useQueryClient>, ws: string) {
  for (const key of [
    "market",
    "market-item",
    "installations",
    "connector-defs",
    "nodes",
    "templates",
    "prompt-packs",
  ]) {
    void qc.invalidateQueries({ queryKey: key === "market" ? [key] : [key, ws] });
  }
  void qc.invalidateQueries({ queryKey: ["market-item"] });
}

export function useInstallMarketItem(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (itemKey: string) =>
      api.post<Installation>(`/workspaces/${ws}/market/install`, { item_key: itemKey }),
    onSuccess: () => invalidateMarket(qc, ws),
  });
}

export function useInstallations(ws: string) {
  return useQuery({
    queryKey: ["installations", ws],
    queryFn: () => api.get<Installation[]>(`/workspaces/${ws}/market/installations`),
    enabled: Boolean(ws),
  });
}

export function useUninstall(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/workspaces/${ws}/market/installations/${id}`),
    onSuccess: () => invalidateMarket(qc, ws),
  });
}

export function useTemplates(ws: string) {
  return useQuery({
    queryKey: ["templates", ws],
    queryFn: () => api.get<Template[]>(`/workspaces/${ws}/templates`),
    enabled: Boolean(ws),
  });
}

export function usePromptPacks(ws: string) {
  return useQuery({
    queryKey: ["prompt-packs", ws],
    queryFn: () => api.get<PromptPack[]>(`/workspaces/${ws}/prompt-packs`),
    enabled: Boolean(ws),
  });
}

// ---------- 공개 앱 ----------
export function usePublicApp(token: string) {
  return useQuery({
    queryKey: ["public-app", token],
    queryFn: () => apiFetch<PublicApp>(`/public/apps/${token}`),
    retry: false,
  });
}

export function sendPublicChat(
  token: string,
  body: {
    message: string;
    session_id?: string;
    input?: Record<string, unknown>;
    files?: string[];
  },
  onEvent: (ev: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamSSE(`/public/apps/${token}/chat`, { method: "POST", body, onEvent, signal });
}
