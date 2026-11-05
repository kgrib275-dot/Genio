// v0.6 API 훅: MCP 서버로 게시(앱 기능 mcp) (docs/api.md v0.6)
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { AppDetailV2 } from "@/lib/api/types";

// ---------------- MCP ----------------
export interface McpFeature {
  enabled: boolean;
  tool_name: string;
  description: string;
}

export const DEFAULT_MCP: McpFeature = { enabled: false, tool_name: "", description: "" };

export function mcpOf(app: AppDetailV2 | undefined): McpFeature {
  const raw = (app?.features as { mcp?: Partial<McpFeature> } | null | undefined)?.mcp;
  return { ...DEFAULT_MCP, ...(raw ?? {}) };
}

export function useSaveMcp(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mcp: McpFeature) => api.patch<AppDetailV2>(`/apps/${appId}/features`, { mcp }),
    onSuccess: (data) => {
      qc.setQueryData(["app", appId], data);
    },
  });
}

/** 도구 이름을 미리 보여 주기(서버 규칙과 같게: 영문·숫자만, 없으면 app_<id 앞 8자리>) */
export function previewToolName(appName: string, appId: string, custom: string): string {
  const c = custom.replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");
  if (c) return c.slice(0, 64);
  const slug = appName
    .replace(/[^A-Za-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase()
    .slice(0, 48);
  return slug || `app_${appId.replace(/-/g, "").slice(0, 8)}`;
}

/** MCP 클라이언트 설정 예시(Claude Desktop은 mcp-remote 다리를 거친다) */
export function mcpConfigSnippets(url: string, key: string, name: string) {
  const desktop = JSON.stringify(
    {
      mcpServers: {
        [name]: {
          command: "npx",
          args: ["-y", "mcp-remote", url, "--header", `Authorization:Bearer ${key}`],
        },
      },
    },
    null,
    2,
  );
  const http = JSON.stringify(
    { mcpServers: { [name]: { type: "http", url, headers: { Authorization: `Bearer ${key}` } } } },
    null,
    2,
  );
  const cli = `claude mcp add --transport http ${name} ${url} --header "Authorization: Bearer ${key}"`;
  return { desktop, http, cli };
}

// 외부 추적 설정 훅은 v0.9에서 lib/api/trace.ts로 옮겼다.
