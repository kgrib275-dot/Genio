import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import { api } from "@/lib/api/client";
import { FinderCard } from "./FinderCard";

vi.mock("@/lib/api/client", () => ({ api: { get: vi.fn(), post: vi.fn() } }));

const trends = {
  updated_at: "2026-11-23T03:00:00+00:00",
  mcp_new_total: 12,
  mcp_new_today: 2,
  mcp_new: [
    {
      name: "io.example/fresh",
      title: "fresh",
      description: "새로 나온 서비스",
      version: "1.0.0",
      repository: "https://github.com/example/fresh",
      website: "",
      installable: true,
      remotes: [{ url: "https://fresh.example.com/mcp", headers: [] }],
      updated_at: "2026-11-23T01:00:00Z",
    },
  ],
  n8n_new: [
    {
      id: 7,
      name: "새 템플릿",
      description: "최근에 올라온 템플릿",
      views: 3,
      author: "maker",
      services: ["Slack"],
      created_at: "2026-11-22",
      url: "https://n8n.io/workflows/7",
    },
  ],
  n8n_popular: [
    {
      id: 1954,
      name: "AI agent chat",
      description: "많이 쓰는 템플릿",
      views: 780399,
      author: "n8n",
      services: ["AI Agent"],
      created_at: "2023-10-03",
      url: "https://n8n.io/workflows/1954",
    },
  ],
  errors: [],
};

function renderCard() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <FinderCard ws="w1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.get).mockImplementation((url: string) =>
    Promise.resolve(url.includes("/catalog/trends") ? trends : { external_catalog: true }),
  );
});

test("처음에는 이번 주 새 소식이 열리고 새 서비스·인기 템플릿이 보인다", async () => {
  renderCard();
  expect(await screen.findByText("새로 나온 서비스")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "이번 주 새 소식" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.getByText(/오늘 새로 올라온 서비스 2개/)).toBeInTheDocument();
  expect(screen.getByText("최근에 올라온 템플릿")).toBeInTheDocument();
  expect(screen.getByText("많이 쓰는 템플릿")).toBeInTheDocument();
  expect(screen.getByText(/조회 780,399/)).toBeInTheDocument();
  // 바로 연결할 수 있는 서비스에는 '연결하기'가 있고, 템플릿에는 '가져오기'가 있다
  expect(screen.getByRole("button", { name: "연결하기" })).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "가져오기" })).toHaveLength(2);
});

test("꺼져 있으면 켜는 방법을 안내하고 목록을 부르지 않는다", async () => {
  vi.mocked(api.get).mockImplementation(() => Promise.resolve({ external_catalog: false }));
  renderCard();
  expect(await screen.findByText(/아직 켜지 않았어요/)).toBeInTheDocument();
  expect(vi.mocked(api.get).mock.calls.some(([u]) => String(u).includes("/catalog/trends"))).toBe(
    false,
  );
});

test("탭으로 서비스 찾기와 n8n 템플릿 검색을 오간다", async () => {
  renderCard();
  fireEvent.click(await screen.findByRole("tab", { name: "서비스 연결" }));
  expect(await screen.findByLabelText("서비스 검색")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "n8n 템플릿" }));
  expect(await screen.findByLabelText("n8n 템플릿 검색")).toBeInTheDocument();
  expect(screen.queryByLabelText("서비스 검색")).not.toBeInTheDocument();
  expect(screen.getByText(/n8n의 공개 무료 템플릿/)).toBeInTheDocument();
});
