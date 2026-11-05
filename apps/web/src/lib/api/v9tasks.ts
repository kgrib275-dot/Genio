// v0.9 사람 단계: 일 전달(사람·역할 목록, 전달하기) API 훅
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { HumanTask } from "@/lib/api/v5a";

export interface ForwardTargets {
  users: { id: string; name: string; role: string }[];
  roles: { id: string; name: string }[];
}

export function useForwardTargets(ws: string, enabled: boolean) {
  return useQuery({
    queryKey: ["forward-targets", ws],
    queryFn: () => api.get<ForwardTargets>(`/workspaces/${ws}/tasks/forward-targets`),
    enabled: Boolean(ws) && enabled,
    staleTime: 60_000,
  });
}

export function useForwardTask(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; to_user_id?: string; to_role?: string; comment?: string }) => {
      const { id, ...body } = v;
      return api.post<HumanTask>(`/workspaces/${ws}/tasks/${id}/forward`, body);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tasks", ws] });
      void qc.invalidateQueries({ queryKey: ["tasks-count", ws] });
    },
  });
}
