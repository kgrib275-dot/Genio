import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, test, vi } from "vitest";
import { ActivationFunnel } from "./ActivationFunnel";

vi.mock("@/lib/api/client", () => ({
  api: {
    get: vi.fn().mockResolvedValue({
      steps: [
        { label: "가입한 멤버", count: 4, rate: 1 },
        { label: "앱을 만든 멤버", count: 2, rate: 0.5 },
        { label: "다른 사람이 쓴 앱", count: 1, rate: null },
      ],
    }),
  },
}));

test("단계별 인원과 비율을 보여 준다", async () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ActivationFunnel ws="w1" />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("앱을 만든 멤버")).toBeInTheDocument();
  expect(screen.getByText("2 (50%)")).toBeInTheDocument();
});
