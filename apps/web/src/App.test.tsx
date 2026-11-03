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
  expect(await screen.findByRole("heading", { name: "로그인" })).toBeInTheDocument();
  expect(screen.getByText("제니오")).toBeInTheDocument();
});
