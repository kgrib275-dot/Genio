// v0.8 전체 검색창(Ctrl+K) API 훅
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface PaletteItem {
  id: string;
  title: string;
  subtitle: string;
  /** 눌렀을 때 가는 화면 주소 */
  to: string;
  /** 앱의 이모지 아이콘 */
  icon?: string;
}

export interface PaletteGroup {
  kind: string;
  label: string;
  items: PaletteItem[];
}

export interface PaletteResult {
  query: string;
  groups: PaletteGroup[];
}

/** 이 사용자의 역할이 볼 수 있는 것만 돌아온다. 검색어가 비면 화면(메뉴) 바로 가기만. */
export function usePaletteSearch(ws: string, q: string, enabled: boolean) {
  return useQuery({
    queryKey: ["palette", ws, q],
    queryFn: () =>
      api.get<PaletteResult>(`/workspaces/${ws}/search?q=${encodeURIComponent(q)}&limit=6`),
    enabled: enabled && Boolean(ws),
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  });
}
