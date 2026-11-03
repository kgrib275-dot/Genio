// v0.5 A: 작업함(승인·질문·배정), 링크 처리, 챗↔흐름(늦게 온 결과·상담원 전환), 배포 대상 사람
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiFetch } from "@/lib/api/client";
import type { ConversationSummary, Deployment, PublicFeatures, Role } from "@/lib/api/types";

// ---------------- 타입 ----------------
export type TaskKind = "approval" | "question" | "assignment";
export type TaskStatus = "open" | "done" | "cancelled";

export interface TaskField {
  key: string;
  label: string;
  type: "text" | "number" | "paragraph" | "choice";
  options?: string[];
  required?: boolean;
}

export interface HumanTask {
  id: string;
  app_id?: string;
  app_name: string;
  run_id?: string | null;
  node_id?: string;
  kind: TaskKind;
  title: string;
  detail: string;
  fields: TaskField[];
  assignee_user_id?: string | null;
  assignee_role: Role | null;
  status: TaskStatus;
  response: Record<string, unknown>;
  due_at: string | null;
  created_at: string;
  completed_at: string | null;
  can_act?: boolean;
}

export interface CompleteTaskBody {
  approved?: boolean;
  values?: Record<string, unknown>;
  comment?: string;
}

export const TASK_KIND_LABEL: Record<TaskKind, string> = {
  approval: "승인",
  question: "질문",
  assignment: "할 일",
};

export const TASK_STATUS_LABEL: Record<TaskStatus, string> = {
  open: "기다리는 중",
  done: "끝남",
  cancelled: "취소됨",
};

export interface HandoffFeature {
  enabled: boolean;
  keywords?: string[];
  message?: string;
}

/** 공개 기능 설정 + 상담원 전환 */
export type FeaturesWithHandoff = PublicFeatures & { handoff?: HandoffFeature };

export interface SessionState {
  status: "bot" | "handoff" | "closed";
  waiting: boolean;
  last_message_at: string | null;
}

export type ConversationWithStatus = ConversationSummary & {
  status?: "bot" | "handoff" | "closed";
};

export type DeploymentWithUsers = Deployment & { allowed_users?: string[] };

// ---------------- 작업함 ----------------
export function useTasks(ws: string, opts: { status: TaskStatus | "all"; mine: boolean }) {
  return useQuery({
    queryKey: ["tasks", ws, opts.status, opts.mine],
    queryFn: () =>
      api.get<HumanTask[]>(
        `/workspaces/${ws}/tasks?status=${opts.status}${opts.mine ? "&mine=true" : ""}`,
      ),
    enabled: Boolean(ws),
    refetchInterval: 30_000,
  });
}

/** 메뉴 배지: 내가 처리할 열린 일 수 */
export function useOpenTaskCount(ws: string) {
  return useQuery({
    queryKey: ["tasks-count", ws],
    queryFn: () => api.get<{ open: number }>(`/workspaces/${ws}/tasks/count`),
    enabled: Boolean(ws),
    refetchInterval: 60_000,
    staleTime: 20_000,
  });
}

function useInvalidateTasks(ws: string) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["tasks", ws] });
    void qc.invalidateQueries({ queryKey: ["tasks-count", ws] });
  };
}

export function useCompleteTask(ws: string) {
  const done = useInvalidateTasks(ws);
  return useMutation({
    mutationFn: (v: { id: string } & CompleteTaskBody) => {
      const { id, ...body } = v;
      return api.post<HumanTask>(`/workspaces/${ws}/tasks/${id}/complete`, body);
    },
    onSuccess: done,
  });
}

export function useCancelTask(ws: string) {
  const done = useInvalidateTasks(ws);
  return useMutation({
    mutationFn: (id: string) => api.post<HumanTask>(`/workspaces/${ws}/tasks/${id}/cancel`),
    onSuccess: done,
  });
}

// ---------------- 링크(로그인 없이) ----------------
export function usePublicTask(token: string) {
  return useQuery({
    queryKey: ["public-task", token],
    queryFn: () => api.get<HumanTask>(`/public/tasks/${encodeURIComponent(token)}`),
    enabled: Boolean(token),
    retry: false,
  });
}

export function useCompletePublicTask(token: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CompleteTaskBody) =>
      api.post<HumanTask>(`/public/tasks/${encodeURIComponent(token)}`, body),
    onSuccess: (t) => qc.setQueryData(["public-task", token], t),
  });
}

// ---------------- 공개 챗: 대화 상태·상담원 연결 ----------------
export function fetchSessionState(token: string, sessionId: string): Promise<SessionState> {
  return apiFetch<SessionState>(
    `/public/apps/${token}/sessions/${encodeURIComponent(sessionId)}/state`,
  );
}

export function requestHandoff(
  token: string,
  sessionId: string,
): Promise<{ status: string; message: { id: string; content: string } | null }> {
  return api.post(`/public/apps/${token}/sessions/${encodeURIComponent(sessionId)}/handoff`);
}

// ---------------- 상담원 응대(운영자) ----------------
export function useHandoffConversations(appId: string, enabled = true) {
  return useQuery({
    queryKey: ["conversations-handoff", appId],
    queryFn: () =>
      api.get<ConversationWithStatus[]>(`/apps/${appId}/conversations?status=handoff&size=100`),
    enabled: Boolean(appId) && enabled,
    refetchInterval: 15_000,
  });
}

export function useAgentReply(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { conversationId: string; content: string }) =>
      api.post(`/conversations/${v.conversationId}/reply`, { content: v.content }),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: ["conversation-messages", v.conversationId] });
      void qc.invalidateQueries({ queryKey: ["conversations-handoff", appId] });
    },
  });
}

export function useCloseHandoff(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (conversationId: string) =>
      api.post<{ id: string; status: string }>(`/conversations/${conversationId}/close`),
    onSuccess: (_d, id) => {
      void qc.invalidateQueries({ queryKey: ["conversation-messages", id] });
      void qc.invalidateQueries({ queryKey: ["conversations-handoff", appId] });
      void qc.invalidateQueries({ queryKey: ["conversations", appId] });
    },
  });
}

// ---------------- 배포: 누가 쓸 수 있나 ----------------
export function useUpdateDeploymentAccess(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      id: string;
      access?: "workspace" | "roles" | "public";
      allowed_roles?: Role[];
      allowed_users?: string[];
    }) => {
      const { id, ...body } = v;
      return api.patch<DeploymentWithUsers>(`/deployments/${id}`, body);
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["deployments", appId] }),
  });
}

export function useCreateDeploymentWithUsers(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      channel: Deployment["channel"];
      access: Deployment["access"];
      allowed_roles?: Role[];
      allowed_users?: string[];
      version?: number;
    }) => api.post<DeploymentWithUsers>(`/apps/${appId}/deployments`, v),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["deployments", appId] });
      void qc.invalidateQueries({ queryKey: ["app", appId] });
      void qc.invalidateQueries({ queryKey: ["apps"] });
    },
  });
}

// ---------------- 앱 기능: 상담원 연결 ----------------
export function useSaveHandoff(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (handoff: HandoffFeature) =>
      api.patch<unknown>(`/apps/${appId}/features`, { handoff }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["app", appId] }),
  });
}
