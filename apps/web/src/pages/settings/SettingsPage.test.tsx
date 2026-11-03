import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { Me } from "@/lib/api/types";
import SettingsPage from "@/pages/settings/SettingsPage";
import { mockFetch, type Call } from "@/test/mockFetch";

const ME: Me = {
  id: "u1",
  email: "kim@example.com",
  name: "김빌더",
  workspaces: [
    { id: "w1", name: "본사", slug: "hq", role: "owner" },
    { id: "w2", name: "연구소", slug: "lab", role: "builder" },
  ],
  preferences: {
    theme: "light",
    font_size: "normal",
    default_workspace_id: null,
    enter_to_send: true,
  },
};

let calls: Call[] = [];

function renderPage() {
  calls = mockFetch({
    "/me": ME,
    "PATCH /me": (c: Call) => ({
      ...ME,
      ...(c.body as object),
      preferences: {
        ...ME.preferences,
        ...((c.body as { preferences?: object }).preferences ?? {}),
      },
    }),
    "POST /me/password": { ok: true },
  });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const patches = () => calls.filter((c) => c.method === "PATCH" && c.path === "/me");

describe("내 설정", () => {
  beforeEach(() => {
    document.documentElement.className = "";
    window.localStorage.clear();
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("테마·글자 크기·기본 워크스페이스·Enter 보내기·이름을 알맞은 본문으로 저장한다", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("radio", { name: "테마 어둡게" }));
    await waitFor(() => expect(patches().at(-1)?.body).toEqual({ preferences: { theme: "dark" } }));
    expect(document.documentElement).toHaveClass("dark");

    fireEvent.click(screen.getByRole("radio", { name: /크게/ }));
    await waitFor(() =>
      expect(patches().at(-1)?.body).toEqual({ preferences: { font_size: "large" } }),
    );

    fireEvent.change(screen.getByLabelText("기본 워크스페이스"), { target: { value: "w2" } });
    await waitFor(() =>
      expect(patches().at(-1)?.body).toEqual({ preferences: { default_workspace_id: "w2" } }),
    );

    fireEvent.click(screen.getByRole("switch", { name: "Enter로 보내기" }));
    await waitFor(() =>
      expect(patches().at(-1)?.body).toEqual({ preferences: { enter_to_send: false } }),
    );

    fireEvent.change(screen.getByLabelText("이름"), { target: { value: "김제니" } });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(patches().at(-1)?.body).toEqual({ name: "김제니" }));
    expect(screen.getByLabelText("이메일")).toHaveAttribute("readonly");
  });

  it("새 비밀번호 확인이 다르면 보내지 않고, 맞으면 지금·새 비밀번호를 보낸다", async () => {
    renderPage();
    fireEvent.change(await screen.findByLabelText("지금 비밀번호"), {
      target: { value: "old-pass-1" },
    });
    fireEvent.change(screen.getByLabelText("새 비밀번호"), { target: { value: "new-pass-12" } });
    fireEvent.change(screen.getByLabelText("새 비밀번호 확인"), {
      target: { value: "new-pass-13" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("새 비밀번호가 서로 달라요.");
    const submit = screen.getByRole("button", { name: "비밀번호 바꾸기" });
    expect(submit).toBeDisabled();
    fireEvent.submit(submit.closest("form") as HTMLFormElement);
    expect(calls.some((c) => c.path === "/me/password")).toBe(false);

    fireEvent.change(screen.getByLabelText("새 비밀번호 확인"), {
      target: { value: "new-pass-12" },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/me/password")?.body).toEqual({
        current_password: "old-pass-1",
        new_password: "new-pass-12",
      }),
    );
  });
});
