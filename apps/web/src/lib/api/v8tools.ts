// v0.8 외부 도구: MCP 서버 연결(연결 정보)과 OpenAPI로 가져온 API 도구 묶음
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

// ---------------- MCP 서버 ----------------
export interface McpServerRow {
  id: string;
  name: string;
  /** 주소 전체에는 비밀이 섞일 수 있어 호스트만 보여 준다 */
  host: string;
  has_token: boolean;
  created_at: string;
}

export interface McpTool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface McpToolsResult {
  ok: boolean;
  message: string;
  tools: McpTool[];
}

export interface NewMcpServer {
  name: string;
  url: string;
  token?: string;
  header_name?: string;
}

export function useMcpServers(ws: string, enabled = true) {
  return useQuery({
    queryKey: ["mcp-servers", ws],
    queryFn: () => api.get<McpServerRow[]>(`/workspaces/${ws}/mcp/servers`),
    enabled: Boolean(ws) && enabled,
  });
}

export function useCreateMcpServer(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: NewMcpServer) =>
      api.post<{ id: string; name: string; host: string; has_token: boolean }>(
        `/workspaces/${ws}/mcp/servers`,
        v,
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["mcp-servers", ws] });
      void qc.invalidateQueries({ queryKey: ["credentials", ws] });
    },
  });
}

/** 서버가 가진 도구 목록. refresh=true면 캐시를 쓰지 않고 다시 연결한다(연결 테스트). */
export function fetchMcpTools(ws: string, id: string, refresh = false): Promise<McpToolsResult> {
  return api.get<McpToolsResult>(
    `/workspaces/${ws}/mcp/servers/${id}/tools${refresh ? "?refresh=1" : ""}`,
  );
}

export function useMcpTools(ws: string, id: string | undefined) {
  return useQuery({
    queryKey: ["mcp-tools", ws, id],
    queryFn: () => fetchMcpTools(ws, id as string),
    enabled: Boolean(ws && id),
    staleTime: 60_000,
  });
}

export function useRefreshMcpTools(ws: string) {
  return useMutation({ mutationFn: (id: string) => fetchMcpTools(ws, id, true) });
}

// ---------------- API 도구(OpenAPI) ----------------
export interface ApiParam {
  name: string;
  in: "path" | "query" | "header";
  required: boolean;
  description: string;
  type: string;
  enum?: unknown[] | null;
  default?: unknown;
}

export interface ApiOperation {
  id: string;
  method: string;
  path: string;
  summary: string;
  parameters: ApiParam[];
  body_schema: Record<string, unknown> | null;
  body_required: boolean;
}

export interface ApiSpecPreview {
  title: string;
  version: string;
  base_url: string;
  operations: ApiOperation[];
  total: number;
  truncated: boolean;
}

export interface ApiSpecSource {
  url?: string;
  text?: string;
}

export interface NewApiToolSet extends ApiSpecSource {
  name: string;
  base_url?: string;
  selected: string[];
  auth_type: "none" | "bearer" | "basic" | "header";
  auth_credential_id?: string;
}

export interface ApiToolSetRow {
  id: string;
  name: string;
  base_url: string;
  tools: number;
  auth_type: string;
  created_at: string;
}

export interface ApiToolSetDetail {
  id: string;
  name: string;
  base_url: string;
  auth_type: string;
  operations: ApiOperation[];
}

export function usePreviewApiTools(ws: string) {
  return useMutation({
    mutationFn: (v: ApiSpecSource) =>
      api.post<ApiSpecPreview>(`/workspaces/${ws}/api-tools/preview`, v),
  });
}

export function useCreateApiToolSet(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: NewApiToolSet) =>
      api.post<{ id: string; name: string; tools: number; base_url: string }>(
        `/workspaces/${ws}/api-tools`,
        v,
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["api-tools", ws] });
      void qc.invalidateQueries({ queryKey: ["credentials", ws] });
    },
  });
}

export function useApiToolSets(ws: string, enabled = true) {
  return useQuery({
    queryKey: ["api-tools", ws],
    queryFn: () => api.get<ApiToolSetRow[]>(`/workspaces/${ws}/api-tools`),
    enabled: Boolean(ws) && enabled,
  });
}

export function useApiToolSet(ws: string, id: string | undefined) {
  return useQuery({
    queryKey: ["api-tool-set", ws, id],
    queryFn: () => api.get<ApiToolSetDetail>(`/workspaces/${ws}/api-tools/${id}`),
    enabled: Boolean(ws && id),
    staleTime: 60_000,
  });
}

// ---------------- 도구 입력 칸(값 칸 만들기) ----------------
export interface ToolField {
  name: string;
  label: string;
  description: string;
  required: boolean;
  kind: "text" | "number" | "boolean" | "choice";
  options: string[];
}

/** JSON Schema의 최상위 속성 중 한 줄 칸으로 만들 수 있는 것들. 하나라도 복잡하면 null(JSON으로 입력). */
export function simpleFields(schema: Record<string, unknown> | undefined): ToolField[] | null {
  const props = schema?.properties as Record<string, Record<string, unknown>> | undefined;
  if (!props || typeof props !== "object") return null;
  const names = Object.keys(props);
  if (names.length === 0 || names.length > 15) return null;
  const required = new Set((schema?.required as string[] | undefined) ?? []);
  const out: ToolField[] = [];
  for (const name of names) {
    const p = props[name] ?? {};
    const type = Array.isArray(p.type) ? String(p.type[0]) : String(p.type ?? "string");
    if (type === "object" || type === "array") return null;
    const options = Array.isArray(p.enum) ? p.enum.map(String) : [];
    out.push({
      name,
      label: String(p.title ?? name),
      description: String(p.description ?? ""),
      required: required.has(name),
      kind:
        options.length > 0
          ? "choice"
          : type === "integer" || type === "number"
            ? "number"
            : type === "boolean"
              ? "boolean"
              : "text",
      options,
    });
  }
  return out;
}

/** 칸에 적은 글을 도구에 넘길 값으로: 숫자·참거짓은 형을 맞추고, {{ }}가 든 글은 그대로 둔다. */
export function coerceFieldValue(kind: ToolField["kind"], raw: string): unknown {
  if (raw === "") return undefined;
  if (raw.includes("{{")) return raw;
  if (kind === "number") {
    const n = Number(raw);
    return Number.isFinite(n) ? n : raw;
  }
  if (kind === "boolean") return raw === "true" ? true : raw === "false" ? false : raw;
  return raw;
}
