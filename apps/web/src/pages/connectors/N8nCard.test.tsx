import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import { api } from "@/lib/api/client";
import { N8nCard } from "./N8nCard";

vi.mock("@/lib/api/client", () => ({ api: { get: vi.fn(), post: vi.fn() } }));

const search = {
  items: [
    {
      id: 101,
      name: "날씨 알림",
      description: "비 오면 슬랙으로 알려요",
      views: 1234,
      author: "maker",
      services: ["Webhook", "Slack"],
      created_at: "",
      url: "https://n8n.io/workflows/101",
    },
  ],
  total: 1,
  page: 1,
  has_more: false,
};

const imported = {
  app: { id: "a1", name: "날씨 알림" },
  report: {
    mode: "n8n",
    dify_version: "",
    converted: [],
    needs_attention: [],
    unsupported: [
      { node: "n3", label: "Slack", dify_type: "slack", message: "직접 연결이 필요해요" },
    ],
    warnings: ["출처: n8n 템플릿 #101"],
    validation_errors: [],
    stats: { converted: 0, needs_attention: 0, unsupported: 1, validation_errors: 0 },
  },
};

function renderCard() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <N8nCard ws="w1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.post).mockReset();
});

test("꺼져 있으면 켜는 방법만 보인다", async () => {
  vi.mocked(api.get).mockResolvedValue({ external_catalog: false });
  renderCard();
  expect(await screen.findByText(/아직 켜지 않았어요/)).toBeInTheDocument();
  expect(screen.queryByLabelText("n8n 템플릿 검색")).not.toBeInTheDocument();
});

test("검색해서 가져오면 결과 보고서가 열린다", async () => {
  vi.mocked(api.get).mockImplementation((url: string) =>
    Promise.resolve(url.includes("/catalog/n8n") ? search : { external_catalog: true }),
  );
  vi.mocked(api.post).mockResolvedValue(imported);
  renderCard();
  fireEvent.change(await screen.findByLabelText("n8n 템플릿 검색"), {
    target: { value: "날씨" },
  });
  fireEvent.click(screen.getByRole("button", { name: "찾기" }));
  expect(await screen.findByText("비 오면 슬랙으로 알려요")).toBeInTheDocument();
  expect(screen.getByText(/쓰는 서비스: Webhook, Slack/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "가져오기" }));
  expect(await screen.findByTestId("dify-report")).toBeInTheDocument();
  expect(api.post).toHaveBeenCalledWith("/workspaces/w1/catalog/n8n/import", { id: 101 });
  expect(screen.getByRole("button", { name: "빌더에서 열기" })).toBeInTheDocument();
});
