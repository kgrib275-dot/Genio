import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { ChatView } from "@/components/chat/ChatView";
import type { ChatSendBody } from "@/lib/api/chat";

function renderChat(sent: ChatSendBody[]) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ChatView
          title="휴가 봇"
          features={{}}
          inputFields={[
            { key: "message", label: "메시지", type: "text", required: true },
            { key: "start", label: "시작일", type: "text", required: true },
            { key: "memo", label: "메모", type: "text", required: false },
          ]}
          transport={{
            send: async (body) => {
              sent.push(body);
            },
          }}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("꼭 적어야 하는 시작 입력 칸", () => {
  it("비워 두면 보내지 않고 어떤 칸인지 알려 준다", async () => {
    const sent: ChatSendBody[] = [];
    renderChat(sent);
    const box = screen.getByPlaceholderText("궁금한 것을 입력해 주세요");
    fireEvent.change(box, { target: { value: "연차 신청" } });
    fireEvent.keyDown(box, { key: "Enter" });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("시작일");
    expect(alert).not.toHaveTextContent("메모");
    expect(sent).toHaveLength(0);
    // 질문 글은 지워지지 않아서 칸만 채우고 다시 보내면 된다
    expect((box as HTMLTextAreaElement).value).toBe("연차 신청");
  });

  it("칸을 채우면 안내가 사라지고 보내진다", async () => {
    const sent: ChatSendBody[] = [];
    renderChat(sent);
    const box = screen.getByPlaceholderText("궁금한 것을 입력해 주세요");
    fireEvent.change(box, { target: { value: "연차 신청" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await screen.findByRole("alert");
    fireEvent.change(screen.getByLabelText("시작일"), { target: { value: "2026-12-24" } });
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]?.input).toMatchObject({ start: "2026-12-24" });
  });
});
