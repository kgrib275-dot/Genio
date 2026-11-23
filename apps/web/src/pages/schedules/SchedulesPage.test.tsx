import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";
import SchedulesPage from "./SchedulesPage";

vi.mock("@/lib/api/client", () => ({
  api: {
    get: vi.fn().mockResolvedValue({
      items: [
        {
          id: "t1",
          app_id: "a1",
          app_name: "아침 요약",
          name: "",
          enabled: true,
          cron: "0 9 * * *",
          timezone: "Asia/Seoul",
          next_run_at: "2030-01-01T00:00:00Z",
          last_run_at: null,
          last_status: null,
        },
      ],
      upcoming: [{ at: "2030-01-01T00:00:00Z", trigger_id: "t1", app_name: "아침 요약", name: "" }],
    }),
  },
}));
vi.mock("@/store/session", () => ({
  useSession: (sel: (s: { workspaceId: string }) => unknown) => sel({ workspaceId: "w1" }),
}));

test("앞으로 7일과 예약 목록을 보여 준다", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <SchedulesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("앞으로 7일")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "아침 요약" })).toBeInTheDocument();
});
