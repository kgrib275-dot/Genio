import { render, screen } from "@testing-library/react";
import { McpToolList } from "@/pages/connectors/McpServerCard";

test("연결 테스트 결과에 도구 이름과 설명이 보인다", () => {
  render(
    <McpToolList
      result={{
        ok: true,
        message: "연결됐어요. 도구 2개를 찾았어요.",
        tools: [
          { name: "search_docs", description: "사내 문서를 찾아요", input_schema: {} },
          { name: "send_mail", description: "", input_schema: {} },
        ],
      }}
    />,
  );
  expect(screen.getByText("연결됐어요. 도구 2개를 찾았어요.")).toBeTruthy();
  expect(screen.getByText("search_docs")).toBeTruthy();
  expect(screen.getByText("사내 문서를 찾아요")).toBeTruthy();
  expect(screen.getByText("send_mail")).toBeTruthy();
});

test("실패하면 이유만 보이고 도구 목록은 없다", () => {
  render(
    <McpToolList
      result={{ ok: false, message: "MCP 서버가 인증을 받아 주지 않았어요.", tools: [] }}
    />,
  );
  expect(screen.getByText("MCP 서버가 인증을 받아 주지 않았어요.")).toBeTruthy();
  expect(screen.queryByRole("list")).toBeNull();
});
