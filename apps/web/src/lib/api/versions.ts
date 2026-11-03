// v0.6 버전 비교
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface DiffField {
  key: string;
  name: string;
  before: string;
  after: string;
}

export interface DiffNode {
  id: string;
  type: string;
  label: string;
  fields?: DiffField[];
}

export interface VersionDiff {
  from: string;
  to: string;
  same: boolean;
  summary: string[];
  nodes_added: DiffNode[];
  nodes_removed: DiffNode[];
  nodes_changed: DiffNode[];
  edges_added: string[];
  edges_removed: string[];
  variables_changed: { key: string; before: string; after: string }[];
  moved: number;
}

/** from·to는 버전 번호 또는 "draft"(작업본) */
export function useVersionDiff(appId: string, from: string | null, to: string) {
  return useQuery({
    queryKey: ["version-diff", appId, from, to],
    queryFn: () =>
      api.get<VersionDiff>(
        `/apps/${appId}/version-diff?from=${encodeURIComponent(from ?? "")}&to=${encodeURIComponent(to)}`,
      ),
    enabled: Boolean(appId && from),
  });
}
