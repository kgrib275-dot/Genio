import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test } from "vitest";
import { authHeaders, setTokens } from "@/lib/api/client";
import { useSession } from "@/store/session";
import { useViewAs, viewAsHeaders } from "@/store/viewAs";
import { ViewAsBanner } from "./ViewAsBanner";
import { ViewAsPicker } from "./ViewAsPicker";

function renderBoth() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ViewAsPicker />
        <ViewAsBanner />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  window.sessionStorage.clear();
  useViewAs.setState({ target: null });
  useSession.getState().setWorkspace("w1", "owner");
});

test("역할을 고르면 화면 권한이 바뀌고 안내 줄이 뜬다", () => {
  renderBoth();
  expect(screen.queryByTestId("viewas-banner")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("권한 미리보기"), { target: { value: "member" } });
  expect(useSession.getState().role).toBe("member");
  expect(useViewAs.getState().target).toEqual({ role: "member", back: "owner" });
  expect(screen.getByTestId("viewas-banner")).toHaveTextContent("사용자 권한으로 미리 보는 중");
});

test("다른 역할로 바꿔도 돌아갈 진짜 역할은 처음 것을 기억한다", () => {
  renderBoth();
  const picker = screen.getByLabelText("권한 미리보기");
  fireEvent.change(picker, { target: { value: "builder" } });
  fireEvent.change(picker, { target: { value: "operator" } });
  expect(useViewAs.getState().target).toEqual({ role: "operator", back: "owner" });
});

test("끝내면 내 진짜 역할로 돌아간다", () => {
  renderBoth();
  fireEvent.change(screen.getByLabelText("권한 미리보기"), { target: { value: "builder" } });
  fireEvent.click(screen.getByRole("button", { name: "내 권한으로 돌아가기" }));
  expect(useSession.getState().role).toBe("owner");
  expect(useViewAs.getState().target).toBeNull();
  expect(screen.queryByTestId("viewas-banner")).not.toBeInTheDocument();
});

test("미리보는 동안에만 요청에 권한 헤더가 붙는다", () => {
  setTokens({ access_token: "tok", refresh_token: "r", token_type: "bearer" });
  expect(viewAsHeaders()).toEqual({});
  expect(authHeaders()["X-Genio-View-As"]).toBeUndefined();
  useViewAs.getState().enter({ role: "member", back: "owner" });
  expect(viewAsHeaders()).toEqual({ "X-Genio-View-As": "member" });
  expect(authHeaders()["X-Genio-View-As"]).toBe("member");
  useViewAs.getState().exit();
  expect(authHeaders()["X-Genio-View-As"]).toBeUndefined();
});
