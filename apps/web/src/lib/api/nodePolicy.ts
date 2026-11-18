// 후속(Z2): 쓸 수 있는 단계 제한(소유자·관리자)
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface NodePolicy {
  blocked_types: string[];
  node_types: { type: string; label: string; category: string; locked: boolean }[];
}

export function useNodePolicy(ws: string) {
  return useQuery({
    queryKey: ["node-policy", ws],
    queryFn: () => api.get<NodePolicy>(`/workspaces/${ws}/node-policy`),
    enabled: Boolean(ws),
  });
}

export function useSaveNodePolicy(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (blocked_types: string[]) =>
      api.put<NodePolicy>(`/workspaces/${ws}/node-policy`, { blocked_types }),
    onSuccess: (data) => qc.setQueryData(["node-policy", ws], data),
  });
}
