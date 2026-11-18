// 운영 준비 1차(B2): 개인정보 가리기 설정(소유자·관리자)
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface PrivacySettings {
  mask_logs: boolean;
  mask_before_ai: boolean;
}

export function usePrivacy(ws: string) {
  return useQuery({
    queryKey: ["privacy", ws],
    queryFn: () => api.get<PrivacySettings>(`/workspaces/${ws}/privacy`),
    enabled: Boolean(ws),
  });
}

export function useUpdatePrivacy(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: Partial<PrivacySettings>) =>
      api.patch<PrivacySettings>(`/workspaces/${ws}/privacy`, v),
    onSuccess: (data) => qc.setQueryData(["privacy", ws], data),
  });
}
