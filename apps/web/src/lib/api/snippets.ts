// v0.8 스니펫(자주 쓰는 단계 묶음) API 훅
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { GraphEdge, GraphNode } from "@/lib/api/types";

export interface Snippet {
  id: string;
  name: string;
  description: string;
  node_count: number;
  node_types: string[];
  /** 다시 골라야 하는 칸(예: "환율 가져오기: 연결 정보") */
  reselect: string[];
  /** 바깥 단계의 값을 쓰던 단계 이름들 */
  outer_refs: string[];
  created_by: string | null;
  created_at: string;
}

export interface SnippetFull extends Snippet {
  graph: { nodes: GraphNode[]; edges: GraphEdge[] };
}

export function useSnippets(ws: string) {
  return useQuery({
    queryKey: ["snippets", ws],
    queryFn: () => api.get<Snippet[]>(`/workspaces/${ws}/snippets`),
    enabled: Boolean(ws),
  });
}

export function fetchSnippet(ws: string, id: string): Promise<SnippetFull> {
  return api.get<SnippetFull>(`/workspaces/${ws}/snippets/${id}`);
}

export function useCreateSnippet(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: {
      name: string;
      description: string;
      nodes: GraphNode[];
      edges: GraphEdge[];
    }) => api.post<SnippetFull>(`/workspaces/${ws}/snippets`, v),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["snippets", ws] }),
  });
}

export function useUpdateSnippet(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; name?: string; description?: string }) =>
      api.patch<Snippet>(`/workspaces/${ws}/snippets/${v.id}`, {
        name: v.name,
        description: v.description,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["snippets", ws] }),
  });
}

export function useDeleteSnippet(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/workspaces/${ws}/snippets/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["snippets", ws] }),
  });
}
