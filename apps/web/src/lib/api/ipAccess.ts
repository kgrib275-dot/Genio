// v0.8 배포 IP 접근 제한 API 훅
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { DeploymentWithUsers } from "@/lib/api/v5a";

export type DeploymentWithIps = DeploymentWithUsers & { allowed_ips?: string[] };

/** 허용 IP·대역을 바꾼다. 빈 목록이면 제한을 푼다. */
export function useUpdateDeploymentIps(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; allowed_ips: string[] }) =>
      api.patch<DeploymentWithIps>(`/deployments/${v.id}`, { allowed_ips: v.allowed_ips }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["deployments", appId] }),
  });
}

/** 지금 이 화면을 연 곳의 IP(서버가 IP 제한과 같은 방식으로 구한다) */
export function fetchMyIp(): Promise<{ ip: string }> {
  return api.get<{ ip: string }>("/me/ip");
}
