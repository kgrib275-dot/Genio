// 운영 준비: 시스템 상태·서버 오류 기록(인스턴스 관리자), 활동 기록 CSV 내보내기
import { useQuery } from "@tanstack/react-query";
import { api, rawRequest, toApiError } from "@/lib/api/client";

export type HealthStatus = "ok" | "warn" | "error" | "unknown";

export interface StatusItem {
  status: HealthStatus;
  label: string;
  detail: string;
}

export interface SystemStatus {
  checked_at: string;
  overall: HealthStatus;
  version: string;
  env: string;
  items: StatusItem[];
  counts: {
    users: number;
    workspaces: number;
    runs_24h: number;
    failed_runs_24h: number;
    server_errors_24h: number;
  };
}

export interface ErrorEvent {
  id: string;
  created_at: string;
  source: string;
  where: string;
  error_type: string;
  message: string;
  request_id: string | null;
  user_id: string | null;
  workspace_id: string | null;
}

export function useSystemStatus(enabled = true) {
  return useQuery({
    queryKey: ["admin-status"],
    queryFn: () => api.get<SystemStatus>("/admin/status"),
    enabled,
    refetchInterval: 30_000,
  });
}

export function useServerErrors(enabled = true) {
  return useQuery({
    queryKey: ["admin-errors"],
    queryFn: () => api.get<ErrorEvent[]>("/admin/errors?limit=1000"),
    enabled,
  });
}

export interface AuditExportFilters {
  area?: string;
  action?: string;
  user?: string;
  days?: string;
  q?: string;
}

/** 활동 기록을 CSV 파일로 받는다(지금 고른 필터 그대로). */
export async function downloadAuditCsv(ws: string, f: AuditExportFilters): Promise<void> {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v) params.set(k, v);
  const res = await rawRequest(`/workspaces/${ws}/audit-logs/export?${params.toString()}`);
  if (!res.ok) throw await toApiError(res);
  const blob = await res.blob();
  const name =
    /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "audit.csv";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
