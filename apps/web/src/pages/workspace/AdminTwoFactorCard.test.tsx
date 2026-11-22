import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";
import { AdminTwoFactorCard } from "./AdminTwoFactorCard";

vi.mock("@/lib/api/client", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ require_admin_2fa: false, without_2fa: ["김관리"] }),
    put: vi.fn(),
  },
}));

test("2단계 인증을 안 쓰는 관리자를 알려 준다", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AdminTwoFactorCard ws="w1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByText(/김관리/)).toBeInTheDocument();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
});
