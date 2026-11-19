import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Member } from "@/lib/api/types";
import { TransferAssetsDialog } from "@/pages/workspace/TransferAssetsDialog";

const members: Member[] = [
  { id: "m1", user_id: "u1", email: "a@x.com", name: "퇴사자", role: "builder" },
  { id: "m2", user_id: "u2", email: "b@x.com", name: "후임", role: "builder" },
  { id: "m3", user_id: "u3", email: "c@x.com", name: "운영자", role: "operator" },
];
const posted: string[] = [];

beforeEach(() => {
  posted.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url).replace("/api/v1", "");
      const json = (b: unknown) =>
        new Response(JSON.stringify(b), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      if (init?.method === "POST") {
        posted.push(`${path} ${init.body}`);
        return json({ apps: 2, api_keys: 1, triggers: 0, data_tables: 0, credentials: 0 });
      }
      return json({
        apps: [
          { id: "a1", name: "휴가 챗봇", status: "published" },
          { id: "a2", name: "주간 보고", status: "draft" },
        ],
        api_keys: 1,
        triggers: 0,
        data_tables: 0,
        credentials: 0,
      });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("TransferAssetsDialog", () => {
  it("넘길 것을 보여 주고, 제작자 이상만 고르게 하며 넘긴다", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <TransferAssetsDialog
          ws="ws1"
          from={members[0] as Member}
          members={members}
          onClose={() => undefined}
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("휴가 챗봇")).toBeInTheDocument();
    const select = screen.getByLabelText("받을 사람");
    const options = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
    expect(options.some((o) => o?.includes("후임"))).toBe(true);
    expect(options.some((o) => o?.includes("운영자"))).toBe(false);
    expect(options.some((o) => o?.includes("퇴사자"))).toBe(false);
    const go = screen.getByRole("button", { name: "넘기기" });
    expect(go).toBeDisabled();
    fireEvent.change(select, { target: { value: "u2" } });
    fireEvent.click(go);
    await waitFor(() =>
      expect(posted).toEqual(['/workspaces/ws1/members/u1/transfer {"to_user_id":"u2"}']),
    );
  });
});
