import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StatusSection } from "@/pages/admin/StatusSection";

const STATUS = {
  checked_at: "2026-11-04T02:00:00Z",
  overall: "warn",
  version: "abc1234",
  env: "prod",
  items: [
    { status: "ok", label: "DB", detail: "응답 3ms" },
    { status: "warn", label: "자동 백업", detail: "하루 넘게 새 백업이 없어요" },
  ],
  counts: { users: 12, workspaces: 3, runs_24h: 40, failed_runs_24h: 2, server_errors_24h: 1 },
};
const ERRORS = [
  {
    id: "e1",
    created_at: "2026-11-04T01:00:00Z",
    source: "api",
    where: "POST /api/v1/apps/{app_id}/runs",
    error_type: "RuntimeError",
    message: "db failed token=****",
    request_id: "req123456",
    user_id: null,
    workspace_id: null,
  },
];

vi.mock("@/lib/api/client", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      get: (path: string) => Promise.resolve(path.startsWith("/admin/status") ? STATUS : ERRORS),
    },
  };
});

test("시스템 상태와 서버 오류 기록을 보여 준다", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <StatusSection />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("살펴볼 것이 있어요")).toBeInTheDocument();
  expect(screen.getByText(/버전 abc1234/)).toBeInTheDocument();
  expect(screen.getByText("하루 넘게 새 백업이 없어요")).toBeInTheDocument();
  const row = await screen.findByRole("button", { name: /RuntimeError/ });
  fireEvent.click(row);
  await waitFor(() => expect(screen.getByText("req123456")).toBeInTheDocument());
  expect(screen.getByText("db failed token=****")).toBeInTheDocument();
});
