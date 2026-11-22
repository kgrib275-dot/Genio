import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import StatusPage from "@/pages/status/StatusPage";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            status: "degraded",
            components: [
              { name: "서비스", status: "ok" },
              { name: "작업 처리", status: "degraded" },
            ],
            announcement: {
              active: true,
              message: "오늘 밤 점검이 있어요.",
              level: "maintenance",
              until: null,
            },
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    ),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("StatusPage", () => {
  it("전체 상태와 구성 요소, 공지를 로그인 없이 보여 준다", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <StatusPage />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("일부 기능이 느리거나 불안정해요")).toBeInTheDocument();
    expect(screen.getByText("작업 처리")).toBeInTheDocument();
    expect(screen.getByText("일부 느림")).toBeInTheDocument();
    expect(screen.getByTestId("announcement")).toHaveTextContent("오늘 밤 점검이 있어요.");
  });
});
