import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { streamSSE, type SSEEvent } from "@/lib/api/sse";
import type { BuilderMessage, BuilderSession } from "@/lib/api/types";

/** 앱의 최신 빌더 대화를 쓰고, 없으면 새로 만든다. */
export function useBuilderSession(appId: string) {
  return useQuery({
    queryKey: ["builder-session", appId],
    queryFn: async () => {
      const list = await api.get<BuilderSession[]>(`/apps/${appId}/builder/sessions`);
      if (list.length > 0 && list[0]) return list[0];
      return api.post<BuilderSession>(`/apps/${appId}/builder/sessions`);
    },
    enabled: Boolean(appId),
    staleTime: Infinity,
  });
}

export function createBuilderSession(appId: string): Promise<BuilderSession> {
  return api.post<BuilderSession>(`/apps/${appId}/builder/sessions`);
}

export function useBuilderMessages(sessionId: string | undefined) {
  return useQuery({
    queryKey: ["builder-messages", sessionId],
    queryFn: () => api.get<BuilderMessage[]>(`/builder/sessions/${sessionId}/messages`),
    enabled: Boolean(sessionId),
    staleTime: Infinity,
  });
}

export interface BuilderSendBody {
  content: string;
  event?: { type: "installed"; item_key: string };
}

export function sendBuilderMessage(
  sessionId: string,
  body: BuilderSendBody,
  onEvent: (ev: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamSSE(`/builder/sessions/${sessionId}/messages`, {
    method: "POST",
    body,
    onEvent,
    signal,
  });
}

export function streamRunEvents(
  runId: string,
  onEvent: (ev: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamSSE(`/runs/${runId}/events`, { onEvent, signal });
}
