import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import AppEvalsPage from "@/pages/apps/AppEvalsPage";
import { splitTerms, formatRate } from "@/lib/api/evals";
import { useSession } from "@/store/session";

const puts: unknown[] = [];

vi.mock("@/lib/api/client", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      get: async (path: string) => {
        if (path.endsWith("/evals/cases"))
          return {
            max_cases: 50,
            cases: [
              {
                id: "c1",
                name: "환불 기간",
                input: { message: "환불은 언제까지?" },
                contains: ["7일"],
                not_contains: [],
                max_seconds: null,
                json_valid: false,
              },
            ],
          };
        if (path.endsWith("/evals"))
          return {
            batches: [
              {
                batch: "b2",
                total: 1,
                finished: 1,
                passed: 0,
                pass_rate: 0,
                avg_seconds: 1,
                cost: 0,
                running: false,
                created_at: null,
                dropped: true,
                previous_pass_rate: 1,
              },
            ],
          };
        return { id: "a1", name: "상담봇", icon: "🤖" };
      },
      put: async (_p: string, body: unknown) => {
        puts.push(body);
        return body;
      },
    },
  };
});

function renderPage() {
  useSession.setState({ role: "builder" } as never);
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/apps/a1/evals"]}>
        <Routes>
          <Route path="apps/:id/evals" element={<AppEvalsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AppEvalsPage", () => {
  it("저장한 질문을 보여 주고 점수가 떨어졌으면 경고한다", async () => {
    renderPage();
    expect(await screen.findByDisplayValue("환불 기간")).toBeInTheDocument();
    expect(screen.getByDisplayValue("환불은 언제까지?")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("100% → 0%");
    expect(screen.getByText("점수 떨어짐")).toBeInTheDocument();
  });

  it("조건을 고쳐 저장하면 서버로 보낸다", async () => {
    renderPage();
    const box = await screen.findByLabelText("질문 1 꼭 들어갈 말");
    fireEvent.change(box, { target: { value: "7일, 환불" } });
    fireEvent.click(screen.getByRole("button", { name: "질문 저장" }));
    await waitFor(() => expect(puts).toHaveLength(1));
    const sent = puts[0] as { cases: { contains: string[] }[] };
    expect(sent.cases[0]?.contains).toEqual(["7일", "환불"]);
  });

  it("도우미 함수", () => {
    expect(splitTerms("a, b\n c,,")).toEqual(["a", "b", "c"]);
    expect(formatRate(0.667)).toBe("67%");
    expect(formatRate(null)).toBe("-");
  });
});
