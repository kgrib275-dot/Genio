import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { SSEEvent } from "@/lib/api/sse";
import SharePage from "@/pages/share/SharePage";

const feedback = vi.fn();
const sentMessages: string[] = [];
let mode: "basic" | "stream" | "hang" = "basic";
let release: (() => void) | null = null;

vi.mock("@/lib/api/resources", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/resources")>();
  return {
    ...actual,
    usePublicApp: () => ({
      isLoading: false,
      error: null,
      data: {
        name: "규정 챗봇",
        description: "",
        icon: "",
        type: "chat",
        access: "public",
        requires_login: false,
        can_use: true,
        input_fields: [{ key: "message", type: "text" }],
        features: {
          opening_statement: "사내 규정을 물어보세요.",
          suggested_questions: ["연차는 며칠인가요?"],
          citations: { enabled: true },
          follow_up: { enabled: true },
        },
        appearance: { primary_color: "#0ea5e9", title: "" },
      },
    }),
    sendPublicChat: async (
      _token: string,
      body: { message: string; session_id?: string },
      onEvent: (ev: SSEEvent) => void,
      signal?: AbortSignal,
    ) => {
      sentMessages.push(body.message);
      if (mode === "stream") {
        onEvent({ event: "session", data: { session_id: "s2" } });
        onEvent({ event: "delta", data: { text: "연차는 ", node_id: "n2" } });
        onEvent({ event: "delta", data: { text: "열다섯 날", node_id: "n2" } });
        await new Promise<void>((r) => {
          release = r;
        });
        onEvent({ event: "answer", data: { text: "**연차는 15일**이에요.", message_id: "m2" } });
        onEvent({ event: "done", data: { session_id: "s2", status: "succeeded" } });
        return;
      }
      if (mode === "hang") {
        onEvent({ event: "session", data: { session_id: "s3" } });
        onEvent({ event: "delta", data: { text: "쓰는 중", node_id: "n2" } });
        await new Promise<void>((_r, reject) => {
          signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        });
        return;
      }
      onEvent({ event: "session", data: { session_id: "s1" } });
      // 출처가 답보다 먼저 와도 그 답에 붙어야 한다
      onEvent({
        event: "citations",
        data: [{ index: 1, filename: "규정.pdf", content: "연차는 15일", score: 0.9 }],
      });
      onEvent({ event: "answer", data: { text: "연차는 15일이에요.", message_id: "m1" } });
      onEvent({ event: "suggestions", data: ["반차도 되나요?"] });
      onEvent({ event: "done", data: { session_id: "s1", status: "succeeded" } });
      await Promise.resolve();
    },
  };
});

vi.mock("@/lib/api/v2", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/v2")>();
  return {
    ...actual,
    sendPublicFeedback: (token: string, messageId: string, rating: string | null) => {
      feedback(token, messageId, rating);
      return Promise.resolve({ ok: true });
    },
  };
});

vi.mock("@/lib/api/client", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    apiFetch: (path: string, opts?: unknown) =>
      path.includes("/sessions/s2/messages")
        ? Promise.resolve([
            { id: "u1", role: "user", content: "예전 질문", created_at: "", feedback: null },
            { id: "a1", role: "assistant", content: "예전 답", created_at: "", feedback: "like" },
          ])
        : actual.apiFetch(path, opts as never),
  };
});

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/share/tok1"]}>
        <Routes>
          <Route path="/share/:token" element={<SharePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  sentMessages.length = 0;
  mode = "basic";
});

describe("공유 챗", () => {
  it("시작 인사·추천 질문을 보여 주고, 답에 출처·이어질 질문·평가를 붙인다", async () => {
    renderPage();
    expect(screen.getByText("사내 규정을 물어보세요.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "연차는 며칠인가요?" }));

    expect(await screen.findByText("연차는 15일이에요.")).toBeInTheDocument();
    expect(sentMessages).toEqual(["연차는 며칠인가요?"]);
    expect(screen.getByRole("button", { name: /규정\.pdf/ })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "반차도 되나요?" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "좋아요" }));
    await waitFor(() => expect(feedback).toHaveBeenCalledWith("tok1", "m1", "like"));
    expect(screen.getByRole("button", { name: "좋아요" })).toHaveAttribute("aria-pressed", "true");

    // 다시 답하기: 같은 질문을 다시 보내고 질문 줄은 늘지 않는다
    fireEvent.click(screen.getByRole("button", { name: "다시 답하기" }));
    await waitFor(() => expect(sentMessages).toEqual(["연차는 며칠인가요?", "연차는 며칠인가요?"]));
    expect(screen.getAllByText("연차는 며칠인가요?")).toHaveLength(1);
  });

  it("답 조각을 실시간으로 보여 주고, 마크다운으로 마무리하며, 지난 대화로 남긴다", async () => {
    mode = "stream";
    renderPage();
    fireEvent.change(screen.getByRole("textbox", { name: "메시지" }), {
      target: { value: "연차 알려줘" },
    });
    fireEvent.click(screen.getByRole("button", { name: "보내기" }));

    expect(await screen.findByText(/연차는 열다섯 날/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "멈추기" })).toBeInTheDocument();
    await act(async () => release?.());
    const strong = await screen.findByText("연차는 15일");
    expect(strong.tagName).toBe("STRONG");
    expect(screen.queryByText(/열다섯 날/)).not.toBeInTheDocument();

    const saved = JSON.parse(window.localStorage.getItem("genio.chat.sessions.tok1") ?? "[]");
    expect(saved[0]).toMatchObject({ session_id: "s2", title: "연차 알려줘" });

    // 새 대화 → 시작 화면, 지난 대화에서 다시 불러오기
    fireEvent.click(screen.getByRole("button", { name: "새 대화" }));
    expect(screen.getByText("사내 규정을 물어보세요.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "지난 대화 보기" }));
    fireEvent.click(screen.getByRole("button", { name: /^연차 알려줘/ }));
    expect(await screen.findByText("예전 답")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "좋아요" })).toHaveAttribute("aria-pressed", "true");
  });

  it("멈추기를 누르면 쓰던 답을 남기고 멈췄다고 알려 준다", async () => {
    mode = "hang";
    renderPage();
    fireEvent.change(screen.getByRole("textbox", { name: "메시지" }), {
      target: { value: "길게 써 줘" },
    });
    fireEvent.click(screen.getByRole("button", { name: "보내기" }));
    expect(await screen.findByText(/쓰는 중/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "멈추기" }));
    expect(await screen.findByText("답을 멈췄어요.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "보내기" })).toBeInTheDocument();
  });
});
