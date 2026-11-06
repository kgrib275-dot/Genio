// v0.3: 개인 설정·프로젝트 API 훅
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setTokens } from "@/lib/api/client";
import type {
  Me,
  Preferences,
  Project,
  ProjectColor,
  ProjectsOverview,
  Tokens,
} from "@/lib/api/types";
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
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { current_password: string; new_password: string }) =>
      api.post<{ ok: boolean } & Partial<Tokens>>("/me/password", v),
    onSuccess: (res) => {
      // 비밀번호를 바꾸면 다른 기기의 로그인은 끊기고, 이 기기는 새 토큰으로 이어 쓴다
      if (res.access_token && res.refresh_token) {
        setTokens({
          access_token: res.access_token,
          refresh_token: res.refresh_token,
          token_type: res.token_type ?? "bearer",
        });
      }
      // 임시 비밀번호를 바꾼 뒤에는 '먼저 바꾸세요' 화면이 사라지도록 내 정보를 다시 읽는다
      void qc.invalidateQueries({ queryKey: ["me"] });
    },
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
