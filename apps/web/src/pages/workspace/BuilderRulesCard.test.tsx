import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BuilderRulesCard } from "@/pages/workspace/BuilderRulesCard";

const puts: unknown[] = [];

vi.mock("@/lib/api/client", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      get: async () => ({ rules: "존댓말로 써.", max_chars: 2000 }),
      put: async (_p: string, body: unknown) => {
        puts.push(body);
        return { rules: (body as { rules: string }).rules, max_chars: 2000 };
      },
    },
  };
});

describe("BuilderRulesCard", () => {
  it("저장된 규칙을 보여 주고 고친 뒤 저장한다", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <BuilderRulesCard ws="w1" />
      </QueryClientProvider>,
    );
    const box = await screen.findByDisplayValue("존댓말로 써.");
    const save = screen.getByRole("button", { name: "저장" });
    expect(save).toBeDisabled();
    fireEvent.change(box, { target: { value: "존댓말로 써.\n알림은 잔디로." } });
    fireEvent.click(save);
    await waitFor(() => expect(puts).toHaveLength(1));
    expect((puts[0] as { rules: string }).rules).toContain("알림은 잔디로.");
  });
});
