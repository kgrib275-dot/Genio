import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ForcePasswordChange } from "@/pages/auth/ForcePasswordChange";

test("임시 비밀번호 화면: 안내 문구와 비활성 버튼", () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ForcePasswordChange name="홍길동" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(screen.getByText("비밀번호를 새로 정해 주세요")).toBeTruthy();
  expect(screen.getByText(/홍길동님/)).toBeTruthy();
  const btn = screen.getByRole("button", { name: /비밀번호 바꾸고 시작하기/ });
  expect((btn as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByLabelText("임시 비밀번호")).toBeTruthy();
});
