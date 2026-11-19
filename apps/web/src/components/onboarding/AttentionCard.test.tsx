import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { AttentionCard } from "@/components/onboarding/AttentionCard";
import { useSession } from "@/store/session";

let payload: unknown = { failed: [], disliked: [] };
beforeEach(() => {
  useSession.setState({ workspaceId: "ws1" });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = String(url).endsWith("/tasks/count") ? { open: 2 } : payload;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

const mount = () =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AttentionCard />
      </MemoryRouter>
    </QueryClientProvider>,
  );

describe("AttentionCard", () => {
  it("승인 대기·실패·싫어요를 한곳에 보여 주고 바로 갈 링크를 준다", async () => {
    payload = {
      failed: [{ app_id: "a1", app_name: "휴가 챗봇", count: 3 }],
      disliked: [{ app_id: "a2", app_name: "규정 봇", count: 1 }],
    };
    mount();
    expect(await screen.findByText(/휴가 챗봇/)).toBeInTheDocument();
    expect(screen.getByText("2건")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /규정 봇/ })).toHaveAttribute("href", "/apps/a2/logs");
  });
});
