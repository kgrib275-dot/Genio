// 외부 서비스 찾기(공식 MCP 레지스트리, ADR 0020)
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface CatalogRemote {
  url: string;
  headers: { name: string; description: string; required: boolean; secret: boolean }[];
}

export interface CatalogItem {
  name: string;
  title: string;
  description: string;
  version: string;
  repository: string;
  website: string;
  installable: boolean;
  remotes: CatalogRemote[];
  updated_at: string;
}

export interface CatalogPage {
  items: CatalogItem[];
  next_cursor: string;
}

export function fetchCatalog(ws: string, q: string, cursor = ""): Promise<CatalogPage> {
  const p = new URLSearchParams();
  if (q) p.set("q", q);
  if (cursor) p.set("cursor", cursor);
  return api.get<CatalogPage>(`/workspaces/${ws}/catalog/mcp?${p.toString()}`);
}

export function useInstallCatalogItem(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { name: string; token?: string }) =>
      api.post<{ id: string; name: string; host: string; has_token: boolean; repository: string }>(
        `/workspaces/${ws}/catalog/mcp/install`,
        v,
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["mcp-servers", ws] });
      void qc.invalidateQueries({ queryKey: ["credentials", ws] });
    },
  });
}

/** 이 회사가 외부 서비스 찾기를 켰는지(안전·규칙 설정과 같은 값을 쓴다) */
export function useCatalogEnabled(ws: string) {
  return useQuery({
    queryKey: ["security", ws],
    queryFn: () => api.get<{ external_catalog: boolean }>(`/workspaces/${ws}/security`),
    enabled: Boolean(ws),
  });
}
