// 후속(C1): 챗 허브 — 내가 쓸 수 있는 배포된 앱 목록
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface HubApp {
  app_id: string;
  name: string;
  icon: string;
  description: string;
  type: string;
  token: string;
}

export function useHub(ws: string) {
  return useQuery({
    queryKey: ["hub", ws],
    queryFn: () => api.get<HubApp[]>(`/workspaces/${ws}/hub`),
    enabled: Boolean(ws),
  });
}
