import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import { useSession } from "@/store/session";
import { supportHeaders, useSupport } from "@/store/support";
import { SupportBanner } from "./SupportBanner";

test("지원 접속 중에만 안내가 보이고, 끝내면 원래 워크스페이스로 돌아간다", () => {
  expect(supportHeaders()).toEqual({});
  useSession.getState().setWorkspace("w2", "admin");
  useSupport.getState().enter({
    id: "w2",
    name: "한빛물산",
    level: "read",
    back: { id: "w1", role: "owner" },
  });
  expect(supportHeaders()).toEqual({ "X-Genio-Support": "1" });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <SupportBanner />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(screen.getByText(/보기만 가능/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "지원 끝내기" }));
  expect(useSupport.getState().target).toBeNull();
  expect(useSession.getState().workspaceId).toBe("w1");
  expect(supportHeaders()).toEqual({});
});
