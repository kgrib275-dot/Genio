import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { BuilderChatView } from "@/components/builder-chat/BuilderChat";
import type { BuilderSendBody } from "@/lib/api/builder";
import type { SSEEvent } from "@/lib/api/sse";
import { useCanvas } from "@/store/canvas";

const sent: BuilderSendBody[] = [];

vi.mock("@/lib/api/builder", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/builder")>();
  return {
    ...actual,
    sendBuilderMessage: async (
      _sid: string,
      body: BuilderSendBody,
      onEvent: (ev: SSEEvent) => void,
    ) => {
      sent.push(body);
      const now = new Date().toISOString();
      const node = { id: "n2", type: "llm", position: { x: 0, y: 0 }, data: { label: "분류" } };
      onEvent({
        event: "user_message",
        data: {
          id: "u" + sent.length,
          role: "user",
          content: body.content,
          graph_patch: null,
          created_at: now,
        },
      });
      onEvent({ event: "text", data: { delta: "분류 단계를 " } });
      onEvent({ event: "text", data: { delta: "추가할게요." } });
      onEvent({ event: "tool_call", data: { id: "t1", name: "add_node", input: { type: "llm" } } });
      onEvent({
        event: "tool_result",
        data: { id: "t1", name: "add_node", ok: true, summary: "n2 추가" },
      });
      onEvent({
        event: "graph_patch",
        data: {
          ops: [{ op: "add_node", node }],
          graph: { version: 1, nodes: [node], edges: [], variables: {} },
        },
      });
      onEvent({
        event: "ask_user",
        data: { question: "어느 채널로 보낼까요?", options: ["#billing", "#tech"] },
      });
      await new Promise((r) => setTimeout(r, 0));
    },
  };
});

function renderChat(enterToSend?: boolean) {
  const qc = new QueryClient();
  if (enterToSend !== undefined)
    qc.setQueryData(["me"], {
      id: "u1",
      email: "a@b.c",
      name: "A",
      workspaces: [],
      preferences: { enter_to_send: enterToSend },
    });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <BuilderChatView sessionId="s1" history={[]} wsId="ws1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BuilderChatView", () => {
  beforeEach(() => {
    sent.length = 0;
    useCanvas.getState().load("app1", { version: 1, nodes: [], edges: [], variables: {} });
  });

  it("스트리밍된 문장·툴 호출·선택지 버튼을 보여 주고 캔버스를 갱신한다", async () => {
    renderChat();
    fireEvent.change(screen.getByLabelText("빌더에게 보낼 메시지"), {
      target: { value: "문의를 분류해 줘" },
    });
    fireEvent.click(screen.getByRole("button", { name: "보내기" }));

    expect(await screen.findByText("분류 단계를 추가할게요.")).toBeInTheDocument();
    expect(screen.getByText("문의를 분류해 줘")).toBeInTheDocument();
    expect(screen.getByText("단계 추가")).toBeInTheDocument();
    expect(screen.getByText("어느 채널로 보낼까요?")).toBeInTheDocument();
    expect(useCanvas.getState().graph.nodes.map((n) => n.id)).toEqual(["n2"]);
    expect(useCanvas.getState().highlights.n2).toBeDefined();

    const option = await screen.findByRole("button", { name: "#billing" });
    await waitFor(() => expect(option).toBeEnabled());
    fireEvent.click(option);
    await waitFor(() =>
      expect(sent.map((s) => s.content)).toEqual(["문의를 분류해 줘", "#billing"]),
    );
  });

  it("Enter로 보내기가 꺼져 있으면 Enter는 줄바꿈, Ctrl+Enter가 보내기다", async () => {
    renderChat(false);
    const box = screen.getByLabelText("빌더에게 보낼 메시지");
    fireEvent.change(box, { target: { value: "첫 줄" } });
    const enter = fireEvent.keyDown(box, { key: "Enter" });
    // 기본 동작(줄바꿈)을 막지 않고, 보내지도 않는다
    expect(enter).toBe(true);
    expect(sent).toHaveLength(0);

    fireEvent.keyDown(box, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(sent.map((s) => s.content)).toEqual(["첫 줄"]));
  });

  it("기본값(켜짐)에서는 Enter로 보내고 Shift+Enter는 줄바꿈이다", async () => {
    renderChat(true);
    const box = screen.getByLabelText("빌더에게 보낼 메시지");
    fireEvent.change(box, { target: { value: "보내기" } });
    expect(fireEvent.keyDown(box, { key: "Enter", shiftKey: true })).toBe(true);
    expect(sent).toHaveLength(0);
    expect(fireEvent.keyDown(box, { key: "Enter" })).toBe(false);
    await waitFor(() => expect(sent.map((s) => s.content)).toEqual(["보내기"]));
  });
});
