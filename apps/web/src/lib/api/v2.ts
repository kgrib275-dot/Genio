// v0.2 API 훅(docs/api.md "v0.2 추가"). 컴포넌트는 fetch 대신 이 훅만 쓴다.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiFetch } from "@/lib/api/client";
import type {
  AdminOverview,
  Annotation,
  ApiKey,
  AppDetailV2,
  AppExport,
  AppFeatures,
  AppStats,
  CreatedAccount,
  ConversationMessage,
  ConversationSummary,
  EnvVar,
  KbChunk,
  KbDocumentV2,
  KbSettings,
  KnowledgeBaseV2,
  NewApiKey,
  Rating,
  RetrievalMethod,
  Role,
  SearchHitV2,
  StoredFile,
  SystemSettings,
  WorkspaceInfo,
  WorkspaceSettings,
} from "@/lib/api/types";

// ---------------- 앱 기능·환경 변수·내보내기 ----------------
function useAppUpdater<V>(appId: string, fn: (v: V) => Promise<AppDetailV2>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (data) => {
      qc.setQueryData(["app", appId], data);
      void qc.invalidateQueries({ queryKey: ["apps"] });
    },
  });
}

export function useSaveFeatures(appId: string) {
  return useAppUpdater(appId, (v: Partial<AppFeatures>) =>
    api.patch<AppDetailV2>(`/apps/${appId}/features`, v),
  );
}

export function useSaveEnvVars(appId: string) {
  return useAppUpdater(appId, (env_vars: EnvVar[]) =>
    api.put<AppDetailV2>(`/apps/${appId}/env-vars`, { env_vars }),
  );
}

export function exportApp(appId: string): Promise<AppExport> {
  return api.get<AppExport>(`/apps/${appId}/export`);
}

export function useImportApp(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: AppExport) => api.post<AppDetailV2>(`/workspaces/${ws}/apps/import`, data),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["apps", ws] }),
  });
}

export function useDuplicateApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (appId: string) => api.post<AppDetailV2>(`/apps/${appId}/duplicate`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["apps"] }),
  });
}

export function useRestoreVersion(appId: string) {
  return useAppUpdater(appId, (version: number) =>
    api.post<AppDetailV2>(`/apps/${appId}/versions/${version}/restore`),
  );
}

// ---------------- 파일 ----------------
export function uploadWorkspaceFile(ws: string, file: File): Promise<StoredFile> {
  const form = new FormData();
  form.append("file", file);
  return api.upload<StoredFile>(`/workspaces/${ws}/files`, form);
}

export function uploadPublicFile(token: string, file: File): Promise<StoredFile> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<StoredFile>(`/public/apps/${token}/files`, { method: "POST", form });
}

export function sendPublicFeedback(
  token: string,
  messageId: string,
  rating: Rating | null,
  comment?: string,
): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/public/apps/${token}/messages/${messageId}/feedback`, {
    method: "POST",
    body: { rating, comment },
  });
}

// ---------------- 로그·주석·모니터링 ----------------
/** 대화 목록(서버에서 페이지·검색). q는 메시지 내용 검색. */
export function useConversations(appId: string, page = 1, size = 30, q = "") {
  return useQuery({
    queryKey: ["conversations", appId, page, size, q],
    queryFn: () =>
      api.get<ConversationSummary[]>(
        `/apps/${appId}/conversations?page=${page}&size=${size}${q ? `&q=${encodeURIComponent(q)}` : ""}`,
      ),
    placeholderData: (prev) => prev,
    enabled: Boolean(appId),
  });
}

export function useConversationMessages(conversationId: string | null) {
  return useQuery({
    queryKey: ["conversation-messages", conversationId],
    queryFn: () => api.get<ConversationMessage[]>(`/conversations/${conversationId}/messages`),
    enabled: Boolean(conversationId),
  });
}

export function useAnnotations(appId: string) {
  return useQuery({
    queryKey: ["annotations", appId],
    queryFn: () => api.get<Annotation[]>(`/apps/${appId}/annotations`),
    enabled: Boolean(appId),
  });
}

export function useCreateAnnotation(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { question: string; answer: string }) =>
      api.post<Annotation>(`/apps/${appId}/annotations`, v),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["annotations", appId] }),
  });
}

export function useUpdateAnnotation(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; question?: string; answer?: string }) =>
      api.patch<Annotation>(`/annotations/${v.id}`, { question: v.question, answer: v.answer }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["annotations", appId] }),
  });
}

export function useDeleteAnnotation(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/annotations/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["annotations", appId] }),
  });
}

export function useAppStats(appId: string, days: number) {
  return useQuery({
    queryKey: ["app-stats", appId, days],
    queryFn: () => api.get<AppStats>(`/apps/${appId}/stats?days=${days}`),
    enabled: Boolean(appId),
  });
}

// ---------------- 앱 API 키 ----------------
export function useApiKeys(appId: string) {
  return useQuery({
    queryKey: ["api-keys", appId],
    queryFn: () => api.get<ApiKey[]>(`/apps/${appId}/api-keys`),
    enabled: Boolean(appId),
  });
}

export function useCreateApiKey(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.post<NewApiKey>(`/apps/${appId}/api-keys`, { name }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["api-keys", appId] }),
  });
}

export function useDeleteApiKey(appId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/api-keys/${id}`),
    onSuccess: () => {
      if (appId) void qc.invalidateQueries({ queryKey: ["api-keys", appId] });
      void qc.invalidateQueries({ queryKey: ["admin-api-keys"] });
    },
  });
}

// ---------------- 지식베이스 확장 ----------------
export function useUpdateKnowledgeBase(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      id: string;
      name?: string;
      settings?: Partial<KbSettings>;
      project_id?: string;
    }) =>
      api.patch<KnowledgeBaseV2>(`/knowledge-bases/${v.id}`, {
        name: v.name,
        settings: v.settings,
        project_id: v.project_id,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["kbs", ws] });
      void qc.invalidateQueries({ queryKey: ["projects", ws] });
    },
  });
}

export function useImportUrl(kbId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (url: string) =>
      api.post<KbDocumentV2>(`/knowledge-bases/${kbId}/documents/url`, { url }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["documents", kbId] });
      void qc.invalidateQueries({ queryKey: ["kbs"] });
    },
  });
}

export function useUpdateDocument(kbId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; metadata: Record<string, string> }) =>
      api.patch<KbDocumentV2>(`/documents/${v.id}`, { metadata: v.metadata }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["documents", kbId] }),
  });
}

export function useReprocessDocument(kbId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<KbDocumentV2>(`/documents/${id}/reprocess`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["documents", kbId] }),
  });
}

export function useChunks(documentId: string | null) {
  return useQuery({
    queryKey: ["chunks", documentId],
    queryFn: () => api.get<KbChunk[]>(`/documents/${documentId}/chunks`),
    enabled: Boolean(documentId),
  });
}

export function useUpdateChunk(documentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; content?: string; enabled?: boolean }) =>
      api.patch<KbChunk>(`/chunks/${v.id}`, { content: v.content, enabled: v.enabled }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["chunks", documentId] }),
  });
}

export interface SearchOptions {
  query: string;
  top_k?: number;
  method?: RetrievalMethod;
  score_threshold?: number;
  metadata_filter?: Record<string, string>;
}

export function searchKnowledgeBaseV2(kbId: string, opts: SearchOptions): Promise<SearchHitV2[]> {
  return api.post<SearchHitV2[]>(`/knowledge-bases/${kbId}/search`, opts);
}

// ---------------- 관리 콘솔 ----------------
export function useAdminOverview(ws: string, days = 14, enabled = true) {
  return useQuery({
    queryKey: ["admin-overview", ws, days],
    queryFn: () => api.get<AdminOverview>(`/workspaces/${ws}/admin/overview?days=${days}`),
    enabled: Boolean(ws) && enabled,
  });
}

export function useWorkspaceInfo(ws: string) {
  return useQuery({
    queryKey: ["workspace", ws],
    queryFn: () => api.get<WorkspaceInfo>(`/workspaces/${ws}`),
    enabled: Boolean(ws),
  });
}

export function useUpdateWorkspace(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { name?: string; settings?: WorkspaceSettings }) =>
      api.patch<WorkspaceInfo>(`/workspaces/${ws}`, v),
    onSuccess: (data) => {
      qc.setQueryData(["workspace", ws], data);
      void qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

export function useRemoveMember(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (memberId: string) => api.del(`/workspaces/${ws}/members/${memberId}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["members", ws] }),
  });
}

export function useTransferOwnership(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (memberId: string) =>
      api.post<{ ok: boolean }>(`/workspaces/${ws}/transfer-ownership`, { member_id: memberId }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["members", ws] });
      void qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

export function useRevokeInvitation(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/workspaces/${ws}/invitations/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["invitations", ws] }),
  });
}

export function useAdminApiKeys(ws: string) {
  return useQuery({
    queryKey: ["admin-api-keys", ws],
    queryFn: () => api.get<ApiKey[]>(`/workspaces/${ws}/admin/api-keys`),
    enabled: Boolean(ws),
  });
}

export function useSystemSettings() {
  return useQuery({
    queryKey: ["system-settings"],
    queryFn: () => api.get<SystemSettings>("/admin/system"),
  });
}

export function useUpdateSystemSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: Partial<Pick<SystemSettings, "allow_signup">>) =>
      api.patch<SystemSettings>("/admin/system", v),
    onSuccess: (data) => {
      qc.setQueryData(["system-settings"], data);
    },
  });
}

export interface NewAccount {
  email: string;
  name: string;
  role: Role;
  password?: string;
}

export function useCreateAccount(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: NewAccount) => api.post<CreatedAccount>(`/workspaces/${ws}/admin/accounts`, v),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["members", ws] }),
  });
}

export function useResetPassword(ws: string) {
  return useMutation({
    mutationFn: (memberId: string) =>
      api.post<{ temporary_password: string }>(
        `/workspaces/${ws}/members/${memberId}/reset-password`,
        {},
      ),
  });
}
