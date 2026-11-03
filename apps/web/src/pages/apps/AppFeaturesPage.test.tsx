import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import AppFeaturesPage from "@/pages/apps/AppFeaturesPage";
import { useSession } from "@/store/session";

const patch = vi.fn();
const APP = {
  id: "a1",
  name: "규정 챗봇",
  icon: "",
  type: "chat",
  features: { opening_statement: "안녕하세요", citations: { enabled: false } },
  env_vars: [],
};

vi.mock("@/lib/api/apps", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/apps")>();
  return {
    ...actual,
    useApp: () => ({ isLoading: false, error: null, data: APP }),
  };
});

vi.mock("@/lib/api/client", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      patch: (path: string, body: unknown) => {
        patch(path, body);
        return Promise.resolve({ ...APP, features: body });
      },
    },
  };
});

describe("앱 기능 화면", () => {
  it("켠 기능과 추천 질문을 PATCH /apps/{id}/features 로 저장한다", async () => {
    useSession.setState({ workspaceId: "ws1", role: "builder" });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/apps/a1/features"]}>
          <Routes>
            <Route path="/apps/:id/features" element={<AppFeaturesPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByLabelText("시작 인사")).toHaveValue("안녕하세요");
    fireEvent.click(screen.getByRole("switch", { name: "출처 표시" }));
    fireEvent.click(screen.getByRole("button", { name: /추천 질문 추가/ }));
    fireEvent.change(screen.getByLabelText("추천 질문 1"), { target: { value: "연차는 며칠?" } });
    fireEvent.click(screen.getByRole("switch", { name: "내용 검열" }));
    fireEvent.change(screen.getByLabelText("금지어"), { target: { value: "욕설, 비방\n광고" } });
    fireEvent.click(screen.getAllByRole("button", { name: "저장" })[0] as HTMLElement);

    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    const [path, body] = patch.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe("/apps/a1/features");
    expect(body).toMatchObject({
      opening_statement: "안녕하세요",
      suggested_questions: ["연차는 며칠?"],
      citations: { enabled: true },
      moderation: { enabled: true, keywords: ["욕설", "비방", "광고"] },
      follow_up: { enabled: false },
      memory: { window: 0 },
    });
  });
});
