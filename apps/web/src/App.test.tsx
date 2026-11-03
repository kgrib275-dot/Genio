import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import App from "@/App";

test("로그인하지 않으면 로그인 화면으로 보낸다", async () => {
  window.localStorage.clear();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("heading", { name: "다시 오신 걸 환영해요" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "로그인" })).toBeInTheDocument();
  // 역할별 데모 계정은 로그인 화면에 보이지 않는다
  expect(screen.queryByText(/데모 계정/)).not.toBeInTheDocument();
  expect(screen.getAllByText("제니오").length).toBeGreaterThan(0);
});
