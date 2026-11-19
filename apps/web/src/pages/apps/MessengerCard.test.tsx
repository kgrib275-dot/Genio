import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MessengerCard } from "@/pages/apps/MessengerCard";

const puts: { path: string; body: unknown }[] = [];
let mode: "ok" | "nodeploy" = "ok";

beforeEach(() => {
  puts.length = 0;
  mode = "ok";
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url).replace("/api/v1", "");
      const json = (b: unknown, status = 200) =>
        new Response(JSON.stringify(b), {
          status,
          headers: { "content-type": "application/json" },
        });
      if (mode === "nodeploy") return json({ deployed: false });
      const status = {
        deployed: true,
        slack_url: "https://g.example.com/api/v1/public/messenger/tok/slack",
        teams_url: "https://g.example.com/api/v1/public/messenger/tok/teams",
        slack: { configured: false, hint: "" },
        teams: { configured: false, hint: "" },
      };
      if (init?.method === "PUT") {
        puts.push({ path, body: JSON.parse(String(init.body)) });
        return json({ ...status, slack: { configured: true, hint: "****gning" } });
      }
      return json(status);
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

function renderCard(editable = true) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MessengerCard appId="app1" editable={editable} />
    </QueryClientProvider>,
  );
}

describe("MessengerCard", () => {
  it("주소를 보여 주고, 비밀값을 저장하면 연결됨으로 바뀐다(비밀값은 다시 보이지 않는다)", async () => {
    renderCard();
    expect(
      await screen.findByText("https://g.example.com/api/v1/public/messenger/tok/slack"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("연결 안 됨")).toHaveLength(2);
    const box = screen.getByLabelText(/Signing Secret/);
    const save = screen.getAllByRole("button", { name: "저장" })[0] as HTMLButtonElement;
    expect(save).toBeDisabled();
    fireEvent.change(box, { target: { value: "s3cret-signing" } });
    fireEvent.click(save);
    await waitFor(() =>
      expect(puts).toEqual([
        { path: "/apps/app1/messenger/slack", body: { secret: "s3cret-signing" } },
      ]),
    );
    expect(await screen.findByText("연결됨")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("s3cret-signing")).toBeNull();
  });

  it("공유 링크로 배포하지 않았으면 먼저 배포하라고 안내한다", async () => {
    mode = "nodeploy";
    renderCard();
    expect(await screen.findByText(/먼저 위에서/)).toBeInTheDocument();
  });

  it("편집 권한이 없으면 아무것도 보이지 않는다", () => {
    const { container } = renderCard(false);
    expect(container).toBeEmptyDOMElement();
  });
});
