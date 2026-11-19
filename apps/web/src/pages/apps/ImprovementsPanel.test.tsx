import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ImprovementsPanel } from "@/pages/apps/ImprovementsPanel";

const calls: { path: string; body: unknown }[] = [];
let items = [
  {
    message_id: "m1",
    question: "재택근무는 며칠까지 돼요?",
    answer: "문서에서 찾지 못했어요.",
    reason: "dislike",
    comment: "틀렸어요",
    count: 2,
    last_at: new Date().toISOString(),
  },
];

beforeEach(() => {
  calls.length = 0;
  items = [...items];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url).replace("/api/v1", "");
      const method = init?.method ?? "GET";
      if (method !== "GET") {
        calls.push({ path, body: init?.body ? JSON.parse(String(init.body)) : null });
        items = [];
      }
      return new Response(
        JSON.stringify(
          method === "GET" ? { open_count: items.length, items } : { annotation_id: "a1" },
        ),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

function renderPanel() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ImprovementsPanel appId="app1" />
    </QueryClientProvider>,
  );
}

describe("ImprovementsPanel", () => {
  it("고칠 질문을 보여 주고, 바른 답을 적어 저장하면 모음에서 사라진다", async () => {
    renderPanel();
    expect(await screen.findByText("재택근무는 며칠까지 돼요?")).toBeInTheDocument();
    expect(screen.getByText("2번 물었어요")).toBeInTheDocument();
    expect(screen.getByText(/틀렸어요/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "바른 답 적기" }));
    const save = screen.getByRole("button", { name: "모범 답변으로 저장" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("바르게 고친 답"), {
      target: { value: "재택은 주 2일까지예요." },
    });
    fireEvent.click(save);
    await waitFor(() =>
      expect(calls).toEqual([
        { path: "/apps/app1/improvements/m1/answer", body: { answer: "재택은 주 2일까지예요." } },
      ]),
    );
    expect(await screen.findByText(/지금 고칠 질문이 없어요/)).toBeInTheDocument();
  });
});
