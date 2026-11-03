import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { SSEEvent } from "@/lib/api/sse";
import SharePage from "@/pages/share/SharePage";

const feedback = vi.fn();
const sentMessages: string[] = [];

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
      },
    }),
    sendPublicChat: async (
      _token: string,
      body: { message: string },
      onEvent: (ev: SSEEvent) => void,
    ) => {
      sentMessages.push(body.message);
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

describe("공유 챗", () => {
  it("시작 인사·추천 질문을 보여 주고, 답에 출처·이어질 질문·평가를 붙인다", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/share/tok1"]}>
          <Routes>
            <Route path="/share/:token" element={<SharePage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByText("사내 규정을 물어보세요.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "연차는 며칠인가요?" }));

    expect(await screen.findByText("연차는 15일이에요.")).toBeInTheDocument();
    expect(sentMessages).toEqual(["연차는 며칠인가요?"]);
    expect(screen.getByRole("button", { name: /규정\.pdf/ })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "반차도 되나요?" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "좋아요" }));
    await waitFor(() => expect(feedback).toHaveBeenCalledWith("tok1", "m1", "like"));
    expect(screen.getByRole("button", { name: "좋아요" })).toHaveAttribute("aria-pressed", "true");
  });
});
