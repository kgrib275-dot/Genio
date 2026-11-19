import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import SharePage from "@/pages/share/SharePage";

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
        features: {},
        appearance: { primary_color: "#0ea5e9", title: "" },
        maintenance: { enabled: true, message: "오후 3시까지 고치는 중이에요." },
      },
    }),
  };
});

describe("SharePage 점검 중", () => {
  it("입력창 대신 점검 안내와 문구를 보여 준다", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/share/tok"]}>
          <Routes>
            <Route path="/share/:token" element={<SharePage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("지금은 점검 중이에요");
    expect(screen.getByText("오후 3시까지 고치는 중이에요.")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});
