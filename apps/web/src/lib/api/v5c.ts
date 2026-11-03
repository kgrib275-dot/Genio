// v0.5 빌더·실행 설명·테스트 입력 API(기능 정의서 S1·S3, 테스트 실행)
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { Run, RunDetail, RunStep } from "@/lib/api/types";

/** 실행 상세(v0.5): 단계마다 한 문장 설명(summary)과 실행 전체 이야기(story) */
export interface StoryStep extends RunStep {
  summary?: string;
}

export interface RunDetailStory extends Omit<RunDetail, "steps"> {
  steps: StoryStep[];
  story?: string[];
}

export interface TestInput {
  name: string;
  input: Record<string, unknown>;
}

export function useTestInputs(appId: string, enabled = true) {
  return useQuery({
    queryKey: ["test-inputs", appId],
    queryFn: () => api.get<TestInput[]>(`/apps/${appId}/test-inputs`),
    enabled: Boolean(appId) && enabled,
  });
}

export function useSaveTestInputs(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (items: TestInput[]) =>
      api.put<TestInput[]>(`/apps/${appId}/test-inputs`, { items }),
    onSuccess: (items) => qc.setQueryData(["test-inputs", appId], items),
  });
}

/** 특정 단계부터 다시 실행: 앞 단계 결과는 지난 실행 것을 그대로 쓴다 */
export function useRerunFromNode(appId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { runId: string; fromNode: string }) =>
      api.post<Run>(`/runs/${v.runId}/rerun`, { from_node: v.fromNode }),
    onSuccess: () => {
      if (appId) void qc.invalidateQueries({ queryKey: ["app-runs", appId] });
    },
  });
}

export interface BuilderMetricsApp {
  app_id: string;
  app_name: string;
  sessions: number;
  seconds_to_valid: number | null;
  user_turns: number;
  edit_turns: number;
  canvas_edits: number;
  builder_ops: number;
  manual_ratio: number | null;
}

export interface BuilderMetrics {
  sessions: number;
  sessions_valid: number;
  avg_seconds_to_valid: number | null;
  avg_user_turns: number | null;
  avg_edit_turns: number | null;
  manual_ratio: number | null;
  apps: BuilderMetricsApp[];
}

export function useBuilderMetrics(ws: string, enabled = true) {
  return useQuery({
    queryKey: ["builder-metrics", ws],
    queryFn: () => api.get<BuilderMetrics>(`/workspaces/${ws}/builder/metrics`),
    enabled: Boolean(ws) && enabled,
  });
}

/** 빌더에게 실패한 실행을 고쳐 달라고 할 때 보낼 문장 */
export function fixRequestMessage(runId: string): string {
  return `이 실행이 왜 실패했는지 보고 고쳐 줘 (실행 ${runId})`;
}

/** 실패 설명(두 줄)을 문제·고치는 방법으로 나눈다 */
export function splitFailure(
  summary: string | undefined,
  fallback: string | null,
): {
  problem: string;
  fix: string;
} {
  const text = summary || fallback || "";
  const [first = "", ...rest] = text.split("\n");
  return {
    problem: first || "실행이 실패했어요.",
    fix: rest.join(" ").trim() || "설정을 확인한 뒤 다시 실행해 보세요.",
  };
}
