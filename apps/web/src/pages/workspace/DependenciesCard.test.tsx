import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { DependenciesCard } from "@/pages/workspace/DependenciesCard";

vi.mock("@/lib/api/client", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      get: async () => ({
        unused_count: 1,
        missing_count: 1,
        apps: [],
        resources: [
          {
            kind: "kb",
            kind_label: "지식베이스",
            id: "k1",
            name: "규정",
            used_by: [{ app_id: "a1", app_name: "상담봇" }],
            unused: false,
          },
          {
            kind: "credential",
            kind_label: "연결 정보",
            id: "c1",
            name: "슬랙",
            used_by: [],
            unused: true,
          },
        ],
      }),
    },
  };
});

describe("DependenciesCard", () => {
  it("쓰는 앱·안 쓰는 자원을 보여 주고 종류로 거른다", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <DependenciesCard ws="w1" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("규정")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "상담봇" })).toHaveAttribute(
      "href",
      "/apps/a1/builder",
    );
    expect(screen.getByText("안 쓰는 중")).toBeInTheDocument();
    expect(screen.getByText(/없어진 자원을 가리키는 설정이 1곳/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "연결 정보" }));
    expect(screen.queryByText("규정")).toBeNull();
    expect(screen.getByText("슬랙")).toBeInTheDocument();
  });
});
