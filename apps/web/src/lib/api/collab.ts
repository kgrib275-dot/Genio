// v0.9 동시 편집(접속 표시·작업본 번호·충돌)과 캔버스 댓글 API.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, rawRequest, toApiError } from "@/lib/api/client";
import { streamSSE, type SSEEvent } from "@/lib/api/sse";
import type { AppDetail } from "@/lib/api/types";

/** 이 브라우저 탭을 구분하는 값. 내가 한 변경이 알림으로 되돌아와도 무시하는 데 쓴다. */
export const CLIENT_ID: string =
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `tab-${Math.random().toString(36).slice(2)}`;

const CLIENT_HEADER = { "X-Genio-Client": CLIENT_ID };

// ---------------- 접속 표시·알림 ----------------
export interface PresenceUser {
  user_id: string;
  name: string;
  color: string;
  node_id: string | null;
  editing: boolean;
  can_edit: boolean;
}

export interface DraftChangedEvent {
  rev: number;
  user_id: string | null;
  client_id: string | null;
}

export interface CommentChangedEvent {
  action: "create" | "edit" | "delete" | "resolve" | "reopen";
  comment_id: string;
  node_id: string | null;
  user_id: string | null;
  client_id: string | null;
}

/** 10초마다 '나 여기 있어요'를 알린다(어떤 단계를 보는지, 고치는 중인지 포함). 실패해도 조용히 넘어간다. */
export function postPresence(
  appId: string,
  body: { node_id?: string | null; editing?: boolean; leave?: boolean },
  keepalive = false,
): Promise<Response> {
  return rawRequest(`/apps/${appId}/presence`, {
    method: "POST",
    body,
    headers: CLIENT_HEADER,
    keepalive,
  });
}

/** 접속 표시·작업본 변경·댓글 변경을 한 줄기로 받는다(SSE). 끊기면 reject, 다시 이어 받는 건 호출한 쪽이 한다. */
export function streamLive(
  appId: string,
  onEvent: (ev: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamSSE(`/apps/${appId}/presence/stream`, { onEvent, signal });
}

// ---------------- 작업본 번호·저장 ----------------
export interface ConflictItem {
  kind: "node" | "edge" | "note" | "variable";
  node_id: string;
  /** "data.template" 같은 칸 이름, 항목 전체는 "*" */
  field: string;
  label: string;
  base: unknown;
  mine: unknown;
  theirs: unknown;
}

export interface DraftConflict {
  rev: number;
  stale: boolean;
  base: unknown;
  mine: unknown;
  theirs: unknown;
  merged: unknown;
  conflicts: ConflictItem[];
}

export type SaveDraftResult =
  | { ok: true; detail: AppDetail & { draft_rev?: number; merged?: boolean } }
  | { ok: false; conflict: DraftConflict };

export function fetchDraft(appId: string): Promise<AppDetail & { draft_rev?: number }> {
  return api.get<AppDetail & { draft_rev?: number }>(`/apps/${appId}`);
}

/** 작업본을 저장한다. 내가 불러온 번호(baseRev)가 서버와 달라 합칠 수 없으면 충돌 정보를 돌려준다. */
export async function saveDraftRev(
  appId: string,
  graph: unknown,
  baseRev: number | null,
): Promise<SaveDraftResult> {
  const res = await rawRequest(`/apps/${appId}/draft`, {
    method: "PUT",
    body: { graph, ...(baseRev === null ? {} : { base_rev: baseRev }) },
    headers: CLIENT_HEADER,
  });
  if (res.status === 409) {
    try {
      const body = (await res.clone().json()) as { detail?: { conflict?: DraftConflict } };
      if (body.detail?.conflict) return { ok: false, conflict: body.detail.conflict };
    } catch {
      // 아래에서 일반 오류로 처리한다
    }
  }
  if (!res.ok) throw await toApiError(res);
  return { ok: true, detail: (await res.json()) as AppDetail & { draft_rev?: number } };
}

// ---------------- 댓글 ----------------
export interface CommentPerson {
  id: string | null;
  name: string;
}

export interface CommentItem {
  id: string;
  node_id: string | null;
  x: number | null;
  y: number | null;
  parent_id: string | null;
  body: string;
  mentions: { id: string; name: string }[];
  resolved: boolean;
  resolved_by: string | null;
  author: CommentPerson;
  created_at: string;
  edited_at: string | null;
}

export interface CommentThread extends CommentItem {
  replies: CommentItem[];
}

export interface Collaborator {
  id: string;
  name: string;
  role: string;
}

export function useComments(appId: string, enabled = true) {
  return useQuery({
    queryKey: ["comments", appId],
    queryFn: () => api.get<CommentThread[]>(`/apps/${appId}/comments`),
    enabled: Boolean(appId) && enabled,
  });
}

export function useCollaborators(appId: string, enabled = true) {
  return useQuery({
    queryKey: ["collaborators", appId],
    queryFn: () => api.get<Collaborator[]>(`/apps/${appId}/collaborators`),
    enabled: Boolean(appId) && enabled,
    staleTime: 5 * 60_000,
  });
}

export interface NewComment {
  body: string;
  node_id?: string | null;
  x?: number | null;
  y?: number | null;
  parent_id?: string | null;
  mentions?: string[];
}

function useCommentMutation<V, R>(appId: string, fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["comments", appId] }),
  });
}

export function useCreateComment(appId: string) {
  return useCommentMutation(appId, (v: NewComment) =>
    rawRequest(`/apps/${appId}/comments`, { method: "POST", body: v, headers: CLIENT_HEADER }).then(
      async (res) => {
        if (!res.ok) throw await toApiError(res);
        return res.json() as Promise<CommentThread>;
      },
    ),
  );
}

export function useEditComment(appId: string) {
  return useCommentMutation(appId, (v: { id: string; body: string; mentions?: string[] }) =>
    rawRequest(`/apps/${appId}/comments/${v.id}`, {
      method: "PATCH",
      body: { body: v.body, ...(v.mentions ? { mentions: v.mentions } : {}) },
      headers: CLIENT_HEADER,
    }).then(async (res) => {
      if (!res.ok) throw await toApiError(res);
      return res.json() as Promise<CommentThread>;
    }),
  );
}

export function useDeleteComment(appId: string) {
  return useCommentMutation(appId, (id: string) =>
    rawRequest(`/apps/${appId}/comments/${id}`, { method: "DELETE", headers: CLIENT_HEADER }).then(
      async (res) => {
        if (!res.ok) throw await toApiError(res);
      },
    ),
  );
}

export function useResolveComment(appId: string) {
  return useCommentMutation(appId, (v: { id: string; resolved: boolean }) =>
    rawRequest(`/apps/${appId}/comments/${v.id}/${v.resolved ? "resolve" : "reopen"}`, {
      method: "POST",
      body: {},
      headers: CLIENT_HEADER,
    }).then(async (res) => {
      if (!res.ok) throw await toApiError(res);
      return res.json() as Promise<CommentThread>;
    }),
  );
}
