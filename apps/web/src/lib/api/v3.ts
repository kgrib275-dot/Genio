// v0.3: 개인 설정·프로젝트 API 훅
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { Me, Preferences, Project, ProjectColor, ProjectsOverview } from "@/lib/api/types";
import { DEFAULT_PREFERENCES } from "@/lib/api/types";

export function preferencesOf(me: Me | undefined): Preferences {
  return { ...DEFAULT_PREFERENCES, ...(me?.preferences ?? {}) };
}

export function useUpdateMe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { name?: string; preferences?: Partial<Preferences> }) =>
      api.patch<Me>("/me", v),
    onSuccess: (me) => qc.setQueryData(["me"], me),
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (v: { current_password: string; new_password: string }) =>
      api.post<{ ok: boolean }>("/me/password", v),
  });
}

export function useProjects(ws: string) {
  return useQuery({
    queryKey: ["projects", ws],
    queryFn: () => api.get<Project[]>(`/workspaces/${ws}/projects`),
    enabled: Boolean(ws),
  });
}

export function useProjectsOverview(ws: string, days: number, enabled = true) {
  return useQuery({
    queryKey: ["projects-overview", ws, days],
    queryFn: () => api.get<ProjectsOverview>(`/workspaces/${ws}/projects/overview?days=${days}`),
    enabled: Boolean(ws) && enabled,
  });
}

export interface ProjectInput {
  name: string;
  description?: string;
  color?: ProjectColor;
  visibility?: "workspace" | "private";
}

function useInvalidateProjects(ws: string) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["projects", ws] });
    void qc.invalidateQueries({ queryKey: ["projects-overview", ws] });
    void qc.invalidateQueries({ queryKey: ["apps", ws] });
    void qc.invalidateQueries({ queryKey: ["kbs", ws] });
  };
}

export function useCreateProject(ws: string) {
  const done = useInvalidateProjects(ws);
  return useMutation({
    mutationFn: (v: ProjectInput) => api.post<Project>(`/workspaces/${ws}/projects`, v),
    onSuccess: done,
  });
}

export function useUpdateProject(ws: string) {
  const done = useInvalidateProjects(ws);
  return useMutation({
    mutationFn: (v: Partial<ProjectInput> & { id: string }) => {
      const { id, ...body } = v;
      return api.patch<Project>(`/projects/${id}`, body);
    },
    onSuccess: done,
  });
}

export function useDeleteProject(ws: string) {
  const done = useInvalidateProjects(ws);
  return useMutation({
    mutationFn: (id: string) => api.del(`/projects/${id}`),
    onSuccess: done,
  });
}

export function useSetProjectMembers(ws: string) {
  const done = useInvalidateProjects(ws);
  return useMutation({
    mutationFn: (v: { id: string; user_ids: string[] }) =>
      api.put<Project>(`/projects/${v.id}/members`, { user_ids: v.user_ids }),
    onSuccess: done,
  });
}

export const PROJECT_COLORS: Record<ProjectColor, string> = {
  indigo: "bg-indigo-500",
  sky: "bg-sky-500",
  emerald: "bg-emerald-500",
  amber: "bg-amber-500",
  rose: "bg-rose-500",
  violet: "bg-violet-500",
  slate: "bg-slate-500",
};
