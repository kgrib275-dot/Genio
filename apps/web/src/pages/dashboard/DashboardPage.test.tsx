import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import type { App, Project } from "@/lib/api/types";
import DashboardPage from "@/pages/dashboard/DashboardPage";
import { useSession } from "@/store/session";
import { mockFetch, type Call } from "@/test/mockFetch";

const PROJECT: Project = {
  id: "p1",
  workspace_id: "w1",
  name: "고객 지원",
  description: "문의 응대 앱 모음",
  color: "emerald",
  visibility: "private",
  created_by: "u1",
  created_by_name: "김빌더",
  created_at: "2026-11-01T00:00:00Z",
  app_count: 1,
  knowledge_base_count: 0,
  members: [{ user_id: "u2", name: "이동료", email: "lee@example.com" }],
  can_manage: true,
};

const app = (id: string, name: string, project_id: string | null): App =>
  ({
    id,
    name,
    project_id,
    workspace_id: "w1",
    type: "chat",
    description: "",
    icon: "",
    status: "draft",
    latest_version: null,
    updated_at: "2026-11-01T00:00:00Z",
    created_at: "2026-11-01T00:00:00Z",
  }) as unknown as App;

function LocationProbe() {
  const loc = useLocation();
  return <p data-testid="loc">{loc.search}</p>;
}

let calls: Call[] = [];

function renderAt(url: string) {
  calls = mockFetch({
    "/me": { id: "u1", email: "kim@example.com", name: "김빌더", workspaces: [] },
    "/workspaces/w1/projects": [PROJECT],
    "/workspaces/w1/apps": (c: Call) =>
      c.path.endsWith("?project=p1")
        ? [app("a1", "문의 분류기", "p1")]
        : c.path.endsWith("?project=none")
          ? [app("a2", "주간 보고", null)]
          : [app("a1", "문의 분류기", "p1"), app("a2", "주간 보고", null)],
    "POST /workspaces/w1/apps": { ...app("a9", "새 앱", "p1") },
  });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route
            path="/"
            element={
              <>
                <DashboardPage />
                <LocationProbe />
              </>
            }
          />
          <Route path="/apps/:id/builder" element={<p>빌더 화면</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const appListCalls = () =>
  calls.filter((c) => c.method === "GET" && c.path.startsWith("/workspaces/w1/apps"));

describe("대시보드 프로젝트", () => {
  beforeEach(() => useSession.getState().setWorkspace("w1", "builder"));
  afterEach(() => vi.unstubAllGlobals());

  it("?project= 로 앱을 거르고, 칩을 누르면 주소와 목록이 바뀐다", async () => {
    renderAt("/?project=p1");
    expect(await screen.findByText("문의 분류기")).toBeInTheDocument();
    expect(appListCalls().at(-1)?.path).toBe("/workspaces/w1/apps?project=p1");
    // 프로젝트 머리글: 이름·설명·공개 범위·설정 버튼
    expect(screen.getByRole("heading", { name: "고객 지원" })).toBeInTheDocument();
    expect(screen.getByText("나와 고른 사람만")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "프로젝트 설정" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "프로젝트 없음" }));
    expect(await screen.findByText("주간 보고")).toBeInTheDocument();
    expect(screen.queryByText("문의 분류기")).not.toBeInTheDocument();
    expect(screen.getByTestId("loc")).toHaveTextContent("?project=none");
    expect(appListCalls().at(-1)?.path).toBe("/workspaces/w1/apps?project=none");

    fireEvent.click(screen.getByRole("button", { name: "전체" }));
    await waitFor(() => expect(appListCalls().at(-1)?.path).toBe("/workspaces/w1/apps"));
    expect(await screen.findByText("문의 분류기")).toBeInTheDocument();
    expect(screen.getByTestId("loc")).toHaveTextContent("");
  });

  it("프로젝트를 보고 있을 때 만든 앱은 그 프로젝트에 들어간다", async () => {
    renderAt("/?project=p1");
    await screen.findByText("문의 분류기");
    fireEvent.change(screen.getByLabelText("만들고 싶은 앱 설명"), {
      target: { value: "회의 메모를 정리해 줘" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^만들기$/ }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
        project_id: "p1",
        description: "회의 메모를 정리해 줘",
      }),
    );
    expect(await screen.findByText("빌더 화면")).toBeInTheDocument();
  });
});
