import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import HubPage from "@/pages/hub/HubPage";
import { useSession } from "@/store/session";

vi.mock("@/lib/api/client", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      get: async () => [
        {
          app_id: "a1",
          name: "상담봇",
          icon: "🤖",
          description: "환불·배송 안내",
          type: "chat",
          token: "t1",
        },
        {
          app_id: "a2",
          name: "메일 요약",
          icon: "📧",
          description: "",
          type: "workflow",
          token: "t2",
        },
      ],
    },
  };
});

function renderHub() {
  useSession.setState({ workspaceId: "w1" } as never);
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <HubPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("HubPage", () => {
  it("쓸 수 있는 앱을 카드로 보여 주고 공유 주소로 연결한다", async () => {
    renderHub();
    const link = await screen.findByRole("link", { name: /상담봇/ });
    expect(link).toHaveAttribute("href", "/share/t1");
    expect(screen.getByText("흐름 앱")).toBeInTheDocument();
  });

  it("이름·설명으로 찾고, 없으면 안내한다", async () => {
    renderHub();
    await screen.findByRole("link", { name: /상담봇/ });
    fireEvent.change(screen.getByLabelText("챗봇 찾기"), { target: { value: "배송" } });
    expect(screen.queryByRole("link", { name: /메일 요약/ })).toBeNull();
    fireEvent.change(screen.getByLabelText("챗봇 찾기"), { target: { value: "없는말" } });
    expect(screen.getByTestId("hub-empty")).toHaveTextContent("찾는 앱이 없어요");
  });
});
