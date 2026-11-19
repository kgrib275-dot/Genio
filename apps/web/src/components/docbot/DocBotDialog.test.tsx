import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { DocBotDialog } from "@/components/docbot/DocBotDialog";
import { useSession } from "@/store/session";

const calls: string[] = [];

beforeEach(() => {
  calls.length = 0;
  useSession.setState({ workspaceId: "ws1" });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url).replace("/api/v1", "");
      calls.push(`${init?.method ?? "GET"} ${path}`);
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { "content-type": "application/json" },
        });
      if (path === "/workspaces/ws1/knowledge-bases") return json({ id: "kb1", name: "휴가 규정" });
      if (path === "/knowledge-bases/kb1/documents") return json({ id: "d1" });
      if (path === "/knowledge-bases/kb1/chatbot")
        return json({ id: "app1", name: "휴가 규정 챗봇" });
      return json({}, 404);
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

function renderDialog() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<DocBotDialog open onClose={() => undefined} />} />
          <Route path="/apps/:id/builder" element={<p>빌더 화면</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DocBotDialog", () => {
  it("파일이 없으면 만들 수 없고, 파일을 고르면 이름이 채워지며 보관함→올리기→챗봇 순서로 만든다", async () => {
    renderDialog();
    const make = screen.getByRole("button", { name: "챗봇 만들기" });
    expect(make).toBeDisabled();
    const input = screen.getByLabelText("문서 고르기");
    const file = new File(["연차는 15일입니다"], "휴가 규정.txt", { type: "text/plain" });
    fireEvent.change(input, { target: { files: [file] } });
    expect(screen.getByDisplayValue("휴가 규정")).toBeInTheDocument();
    expect(screen.getByText("휴가 규정.txt")).toBeInTheDocument();
    fireEvent.click(make);
    expect(await screen.findByText("빌더 화면")).toBeInTheDocument();
    await waitFor(() =>
      expect(calls).toEqual([
        "POST /workspaces/ws1/knowledge-bases",
        "POST /knowledge-bases/kb1/documents",
        "POST /knowledge-bases/kb1/chatbot",
      ]),
    );
  });
});
