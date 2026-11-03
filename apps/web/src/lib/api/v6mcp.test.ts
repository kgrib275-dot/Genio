import { mcpConfigSnippets, mcpOf, previewToolName } from "@/lib/api/v6mcp";

test("도구 이름 미리 보기는 서버 규칙과 같다", () => {
  expect(previewToolName("Echo Bot 앱", "abcd-1234-ef", "")).toBe("echo_bot");
  expect(previewToolName("사내 규정", "abcd-1234-efgh", "")).toBe("app_abcd1234");
  expect(previewToolName("x", "id", "내 도구 v2!")).toBe("v2");
});

test("MCP 설정 예시에 주소와 키가 들어간다", () => {
  const s = mcpConfigSnippets("https://g.example/api/v1/service/mcp", "gk-1", "genio-a");
  expect(JSON.parse(s.desktop).mcpServers["genio-a"].args).toContain("Authorization:Bearer gk-1");
  expect(JSON.parse(s.http).mcpServers["genio-a"].url).toBe("https://g.example/api/v1/service/mcp");
  expect(s.cli).toContain("--transport http genio-a");
});

test("저장된 기능이 없으면 꺼진 기본값", () => {
  expect(mcpOf(undefined)).toEqual({ enabled: false, tool_name: "", description: "" });
});
