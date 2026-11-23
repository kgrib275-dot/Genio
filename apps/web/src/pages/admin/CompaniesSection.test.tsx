import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";
import { CompaniesSection } from "./CompaniesSection";

vi.mock("@/lib/api/client", () => ({
  api: {
    get: vi.fn().mockResolvedValue({
      items: [
        {
          id: "w1",
          name: "한빛물산",
          slug: "hanbit",
          is_instance: false,
          owners: ["김한빛"],
          members: 3,
          apps: 11,
          published_apps: 2,
          month_runs: 40,
          month_cost: 1.5,
          monthly_budget_usd: null,
          last_active_at: null,
          support_access: "read",
        },
      ],
      totals: { workspaces: 1, members: 3, apps: 11, month_runs: 40, month_cost: 1.5 },
    }),
  },
}));

test("회사별 숫자만 보여 준다", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <CompaniesSection />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("한빛물산")).toBeInTheDocument();
  expect(screen.getByText(/소유자 김한빛/)).toBeInTheDocument();
  expect(screen.getByText("사람 3")).toBeInTheDocument();
  expect(screen.getByText("활동 없음")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "도와주기" })).toBeEnabled();
});
