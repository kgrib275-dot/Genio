import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";
import { FinderCard } from "./FinderCard";

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn().mockResolvedValue({ external_catalog: true }), post: vi.fn() },
}));

test("탭으로 서비스 연결과 n8n 템플릿을 오간다", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <FinderCard ws="w1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByLabelText("서비스 검색")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "서비스 연결" })).toHaveAttribute("aria-selected", "true");
  fireEvent.click(screen.getByRole("tab", { name: "n8n 템플릿" }));
  expect(await screen.findByLabelText("n8n 템플릿 검색")).toBeInTheDocument();
  expect(screen.queryByLabelText("서비스 검색")).not.toBeInTheDocument();
  expect(screen.getByText(/n8n의 공개 무료 템플릿/)).toBeInTheDocument();
});
