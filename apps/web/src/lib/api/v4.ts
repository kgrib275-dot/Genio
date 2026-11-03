// v0.4 API 훅: 자동 실행(외부에서 받기·예약), 실행 다시 하기, 데이터 표(docs/api.md v0.4)
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, rawRequest, toApiError } from "@/lib/api/client";
import type {
  DataColumn,
  DataRow,
  DataRowPage,
  DataTable,
  Run,
  ScheduleConfig,
  Trigger,
  TriggerKind,
  WebhookConfig,
} from "@/lib/api/types";

// ---------------- 자동 실행 ----------------
export function useTriggers(appId: string, enabled = true) {
  return useQuery({
    queryKey: ["triggers", appId],
    queryFn: () => api.get<Trigger[]>(`/apps/${appId}/triggers`),
    enabled: Boolean(appId) && enabled,
  });
}

export interface NewTrigger {
  kind: TriggerKind;
  name?: string;
  enabled?: boolean;
  config: Partial<WebhookConfig & ScheduleConfig>;
}

function useInvalidateTriggers(appId: string) {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: ["triggers", appId] });
}

export function useCreateTrigger(appId: string) {
  const done = useInvalidateTriggers(appId);
  return useMutation({
    mutationFn: (v: NewTrigger) => api.post<Trigger>(`/apps/${appId}/triggers`, v),
    onSuccess: done,
  });
}

export function useUpdateTrigger(appId: string) {
  const done = useInvalidateTriggers(appId);
  return useMutation({
    mutationFn: (v: { id: string } & Partial<Omit<NewTrigger, "kind">>) => {
      const { id, ...body } = v;
      return api.patch<Trigger>(`/triggers/${id}`, body);
    },
    onSuccess: done,
  });
}

export function useRotateTriggerToken(appId: string) {
  const done = useInvalidateTriggers(appId);
  return useMutation({
    mutationFn: (id: string) => api.post<Trigger>(`/triggers/${id}/rotate-token`),
    onSuccess: done,
  });
}

export function useRunTriggerNow(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<Run>(`/triggers/${id}/run-now`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["triggers", appId] });
      void qc.invalidateQueries({ queryKey: ["app-runs", appId] });
    },
  });
}

export function useDeleteTrigger(appId: string) {
  const done = useInvalidateTriggers(appId);
  return useMutation({
    mutationFn: (id: string) => api.del(`/triggers/${id}`),
    onSuccess: done,
  });
}

// ---------------- 실행 다시 하기 ----------------
export function useRerun(appId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { runId: string; input?: Record<string, unknown> }) =>
      api.post<Run>(`/runs/${v.runId}/rerun`, v.input ? { input: v.input } : {}),
    onSuccess: () => {
      if (appId) void qc.invalidateQueries({ queryKey: ["app-runs", appId] });
    },
  });
}

// ---------------- 데이터 표 ----------------
export function useDataTables(ws: string, enabled = true) {
  return useQuery({
    queryKey: ["data-tables", ws],
    queryFn: () => api.get<DataTable[]>(`/workspaces/${ws}/data-tables`),
    enabled: Boolean(ws) && enabled,
  });
}

export function useDataTable(id: string) {
  return useQuery({
    queryKey: ["data-table", id],
    queryFn: () => api.get<DataTable>(`/data-tables/${id}`),
    enabled: Boolean(id),
  });
}

export interface DataTableInput {
  name: string;
  description?: string;
  columns?: DataColumn[];
  project_id?: string | null;
}

function useInvalidateTables(ws: string) {
  const qc = useQueryClient();
  return (id?: string) => {
    void qc.invalidateQueries({ queryKey: ["data-tables", ws] });
    if (id) {
      void qc.invalidateQueries({ queryKey: ["data-table", id] });
      void qc.invalidateQueries({ queryKey: ["data-rows", id] });
    }
  };
}

export function useCreateDataTable(ws: string) {
  const done = useInvalidateTables(ws);
  return useMutation({
    mutationFn: (v: DataTableInput) => api.post<DataTable>(`/workspaces/${ws}/data-tables`, v),
    onSuccess: () => done(),
  });
}

export function useUpdateDataTable(ws: string) {
  const done = useInvalidateTables(ws);
  return useMutation({
    mutationFn: (v: { id: string } & Partial<DataTableInput>) => {
      const { id, ...body } = v;
      return api.patch<DataTable>(`/data-tables/${id}`, body);
    },
    onSuccess: (t) => done(t.id),
  });
}

export function useDeleteDataTable(ws: string) {
  const done = useInvalidateTables(ws);
  return useMutation({
    mutationFn: (id: string) => api.del(`/data-tables/${id}`),
    onSuccess: () => done(),
  });
}

export interface RowQuery {
  limit: number;
  offset: number;
  q: string;
}

export function useDataRows(tableId: string, query: RowQuery) {
  const sp = new URLSearchParams({ limit: String(query.limit), offset: String(query.offset) });
  if (query.q.trim()) sp.set("q", query.q.trim());
  return useQuery({
    queryKey: ["data-rows", tableId, query],
    queryFn: () => api.get<DataRowPage>(`/data-tables/${tableId}/rows?${sp.toString()}`),
    enabled: Boolean(tableId),
    placeholderData: (prev) => prev,
  });
}

function useInvalidateRows(tableId: string) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["data-rows", tableId] });
    void qc.invalidateQueries({ queryKey: ["data-tables"] });
  };
}

export function useCreateRow(tableId: string) {
  const done = useInvalidateRows(tableId);
  return useMutation({
    mutationFn: (v: { row_key?: string | null; data: Record<string, unknown> }) =>
      api.post<DataRow>(`/data-tables/${tableId}/rows`, v),
    onSuccess: done,
  });
}

export function useUpdateRow(tableId: string) {
  const done = useInvalidateRows(tableId);
  return useMutation({
    mutationFn: (v: { id: string; row_key?: string | null; data?: Record<string, unknown> }) => {
      const { id, ...body } = v;
      return api.patch<DataRow>(`/data-rows/${id}`, body);
    },
    onSuccess: done,
  });
}

export function useDeleteRow(tableId: string) {
  const done = useInvalidateRows(tableId);
  return useMutation({
    mutationFn: (id: string) => api.del(`/data-rows/${id}`),
    onSuccess: done,
  });
}

export function useImportCsv(ws: string, tableId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api.upload<{ imported: number; columns: DataColumn[] }>(
        `/data-tables/${tableId}/import`,
        form,
      );
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["data-rows", tableId] });
      void qc.invalidateQueries({ queryKey: ["data-table", tableId] });
      void qc.invalidateQueries({ queryKey: ["data-tables", ws] });
    },
  });
}

/** 표를 CSV 파일로 내려받는다(인증 헤더가 필요해 링크 대신 받아서 저장). */
export async function downloadDataTableCsv(table: { id: string; name: string }): Promise<void> {
  const res = await rawRequest(`/data-tables/${table.id}/export.csv`);
  if (!res.ok) throw await toApiError(res);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${table.name || "data"}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
