// 배우기·샘플 API
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface SampleStatus {
  installed: boolean;
  project_id: string | null;
  apps: { id: string; name: string; type: "chat" | "workflow" }[];
}

export function useSampleStatus(ws: string) {
  return useQuery({
    queryKey: ["samples", ws],
    queryFn: () => api.get<SampleStatus>(`/workspaces/${ws}/samples`),
    enabled: Boolean(ws),
  });
}

export function useInstallSamples(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<SampleStatus>(`/workspaces/${ws}/samples`),
    onSuccess: (data) => {
      qc.setQueryData(["samples", ws], data);
      for (const key of ["apps", "projects", "data-tables", "kbs"])
        void qc.invalidateQueries({ queryKey: [key, ws] });
    },
  });
}

const DONE_KEY = "genio.learn.done";

export function readDone(): string[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(DONE_KEY) ?? "[]");
    return Array.isArray(v) ? v.map(String) : [];
  } catch {
    return [];
  }
}

export function writeDone(ids: string[]): void {
  try {
    window.localStorage.setItem(DONE_KEY, JSON.stringify(ids));
  } catch {
    // 기억하지 못해도 강좌는 볼 수 있다
  }
}
