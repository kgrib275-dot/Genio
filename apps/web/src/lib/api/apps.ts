import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type {
  Access,
  App,
  AppDetail,
  AppType,
  Channel,
  Deployment,
  Graph,
  Role,
  Run,
  RunDetail,
  ValidationResult,
  VersionDetail,
  VersionSummary,
} from "@/lib/api/types";

export function useApps(ws: string) {
  return useQuery({
    queryKey: ["apps", ws],
    queryFn: () => api.get<App[]>(`/workspaces/${ws}/apps`),
    enabled: Boolean(ws),
  });
}

export function useApp(appId: string) {
  return useQuery({
    queryKey: ["app", appId],
    queryFn: () => api.get<AppDetail>(`/apps/${appId}`),
    enabled: Boolean(appId),
  });
}

export function useCreateApp(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      name: string;
      type: AppType;
      description?: string;
      icon?: string;
      template_key?: string;
    }) => api.post<AppDetail>(`/workspaces/${ws}/apps`, v),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["apps", ws] }),
  });
}

export function useUpdateApp(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: Partial<Pick<App, "name" | "description" | "icon" | "type">>) =>
      api.patch<AppDetail>(`/apps/${appId}`, v),
    onSuccess: (data) => {
      qc.setQueryData(["app", appId], data);
      void qc.invalidateQueries({ queryKey: ["apps"] });
    },
  });
}

export function useDeleteApp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (appId: string) => api.del(`/apps/${appId}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["apps"] }),
  });
}

export function saveDraft(appId: string, graph: Graph): Promise<AppDetail> {
  return api.put<AppDetail>(`/apps/${appId}/draft`, { graph });
}

export function useVersions(appId: string) {
  return useQuery({
    queryKey: ["versions", appId],
    queryFn: () => api.get<VersionSummary[]>(`/apps/${appId}/versions`),
    enabled: Boolean(appId),
  });
}

export function fetchVersion(appId: string, version: number): Promise<VersionDetail> {
  return api.get<VersionDetail>(`/apps/${appId}/versions/${version}`);
}

export function useSaveVersion(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { graph?: Graph; note?: string }) =>
      api.post<VersionSummary>(`/apps/${appId}/versions`, v),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["versions", appId] });
      void qc.invalidateQueries({ queryKey: ["app", appId] });
    },
  });
}

export function validateGraph(appId: string, graph?: Graph): Promise<ValidationResult> {
  return api.post<ValidationResult>(`/apps/${appId}/validate`, graph ? { graph } : {});
}

export function startRun(
  appId: string,
  input: Record<string, unknown>,
  version?: number,
): Promise<Run> {
  return api.post<Run>(`/apps/${appId}/runs`, version ? { input, version } : { input });
}

export function useAppRuns(appId: string) {
  return useQuery({
    queryKey: ["app-runs", appId],
    queryFn: () => api.get<Run[]>(`/apps/${appId}/runs`),
    enabled: Boolean(appId),
  });
}

export function useRun(runId: string) {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.get<RunDetail>(`/runs/${runId}`),
    enabled: Boolean(runId),
  });
}

export function useApproveRun(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { approved: boolean; comment?: string }) =>
      api.post<RunDetail>(`/runs/${runId}/approve`, v),
    onSuccess: (data) => qc.setQueryData(["run", runId], data),
  });
}

export function useDeployments(appId: string) {
  return useQuery({
    queryKey: ["deployments", appId],
    queryFn: () => api.get<Deployment[]>(`/apps/${appId}/deployments`),
    enabled: Boolean(appId),
  });
}

export function useCreateDeployment(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      channel: Channel;
      access: Access;
      allowed_roles?: Role[];
      version?: number;
    }) => api.post<Deployment>(`/apps/${appId}/deployments`, v),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["deployments", appId] });
      void qc.invalidateQueries({ queryKey: ["app", appId] });
      void qc.invalidateQueries({ queryKey: ["apps"] });
    },
  });
}

export function useDeleteDeployment(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/deployments/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["deployments", appId] }),
  });
}
