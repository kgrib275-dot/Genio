import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import App from "@/App";

vi.mock("@/lib/api/health", () => ({
  useHealth: () => ({ data: { status: "ok", env: "test" }, isError: false }),
}));

test("홈 화면에 서버 연결 상태를 보여 준다", () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(screen.getByText("제니오")).toBeInTheDocument();
  expect(screen.getByTestId("server-status")).toHaveTextContent("서버 연결됨");
});
