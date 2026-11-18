// 후속(O3): 연결 관계 지도 — 어떤 앱이 어떤 자원을 쓰는지
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface DepResource {
  kind: string;
  kind_label: string;
  id: string;
  name: string;
  used_by: { app_id: string; app_name: string }[];
  unused: boolean;
}

export interface DepApp {
  app_id: string;
  name: string;
  uses: { kind: string; id: string; name: string; missing: boolean }[];
}

export interface DepMap {
  resources: DepResource[];
  apps: DepApp[];
  unused_count: number;
  missing_count: number;
}

export function useDependencies(ws: string) {
  return useQuery({
    queryKey: ["dependencies", ws],
    queryFn: () => api.get<DepMap>(`/workspaces/${ws}/dependencies`),
    enabled: Boolean(ws),
  });
}
