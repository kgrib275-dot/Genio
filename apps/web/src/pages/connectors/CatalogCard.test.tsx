import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, test, vi } from "vitest";
import { api } from "@/lib/api/client";
import { CatalogCard } from "./CatalogCard";

vi.mock("@/lib/api/client", () => ({ api: { get: vi.fn(), post: vi.fn() } }));

const page = {
  items: [
    {
      name: "io.example/notes",
      title: "notes",
      description: "메모 서비스",
      version: "1.2.0",
      repository: "https://github.com/example/notes",
      website: "",
      installable: true,
      remotes: [
        {
          url: "https://mcp.example.com/mcp",
          headers: [{ name: "X-API-Key", description: "", required: true, secret: true }],
        },
      ],
      updated_at: "",
    },
    {
      name: "io.example/local",
      title: "local",
      description: "내 컴퓨터용",
      version: "0.1",
      repository: "",
      website: "",
      installable: false,
      remotes: [],
      updated_at: "",
    },
  ],
  next_cursor: "",
};

function renderCard() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CatalogCard ws="w1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.post).mockReset();
});

test("꺼져 있으면 켜는 방법을 안내한다", async () => {
  vi.mocked(api.get).mockResolvedValue({ external_catalog: false });
  renderCard();
  expect(await screen.findByText(/아직 켜지 않았어요/)).toBeInTheDocument();
  expect(screen.queryByLabelText("서비스 검색")).not.toBeInTheDocument();
});

test("검색하고 토큰을 넣어 연결한다", async () => {
  vi.mocked(api.get).mockImplementation((url: string) =>
    Promise.resolve(url.includes("/catalog/mcp") ? page : { external_catalog: true }),
  );
  vi.mocked(api.post).mockResolvedValue({ id: "c1", name: "notes", host: "mcp.example.com" });
  renderCard();
  fireEvent.change(await screen.findByLabelText("서비스 검색"), { target: { value: "notes" } });
  fireEvent.click(screen.getByRole("button", { name: "찾기" }));
  expect(await screen.findByText("메모 서비스")).toBeInTheDocument();
  expect(screen.getByText("바로 연결 불가")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "연결하기" }));
  expect(screen.getByText("mcp.example.com")).toBeInTheDocument();
  const submit = screen.getByRole("button", { name: "이 서비스 연결" });
  expect(submit).toBeDisabled(); // 토큰이 필요한 서비스는 토큰 없이 못 누른다
  fireEvent.change(screen.getByLabelText("접속 토큰"), { target: { value: "tok-1" } });
  fireEvent.click(submit);
  expect(await screen.findByText("연결했어요")).toBeInTheDocument();
  expect(api.post).toHaveBeenCalledWith("/workspaces/w1/catalog/mcp/install", {
    name: "io.example/notes",
    token: "tok-1",
  });
});
