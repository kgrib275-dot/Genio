// 후속(X4): 빌더 상시 규칙(소유자·관리자)
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface BuilderRules {
  rules: string;
  max_chars: number;
}

export function useBuilderRules(ws: string) {
  return useQuery({
    queryKey: ["builder-rules", ws],
    queryFn: () => api.get<BuilderRules>(`/workspaces/${ws}/builder-rules`),
    enabled: Boolean(ws),
  });
}

export function useSaveBuilderRules(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (rules: string) =>
      api.put<BuilderRules>(`/workspaces/${ws}/builder-rules`, { rules }),
    onSuccess: (data) => qc.setQueryData(["builder-rules", ws], data),
  });
}
