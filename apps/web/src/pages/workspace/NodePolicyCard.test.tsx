import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NodePolicyCard } from "@/pages/workspace/NodePolicyCard";

const puts: unknown[] = [];

vi.mock("@/lib/api/client", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/client")>();
  const view = {
    blocked_types: ["http"],
    node_types: [
      { type: "input", label: "입력", category: "흐름", locked: true },
      { type: "code", label: "코드", category: "데이터", locked: false },
      { type: "http", label: "외부 호출", category: "연결", locked: false },
    ],
  };
  return {
    ...actual,
    api: {
      ...actual.api,
      get: async () => view,
      put: async (_p: string, body: unknown) => {
        puts.push(body);
        return { ...view, blocked_types: (body as { blocked_types: string[] }).blocked_types };
      },
    },
  };
});

describe("NodePolicyCard", () => {
  it("막은 단계는 체크되어 있고, 시작·결과 단계는 목록에 없다", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <NodePolicyCard ws="w1" />
      </QueryClientProvider>,
    );
    expect(await screen.findByLabelText(/외부 호출/)).toBeChecked();
    expect(screen.getByLabelText(/코드/)).not.toBeChecked();
    expect(screen.queryByLabelText(/^입력/)).toBeNull();
    fireEvent.click(screen.getByLabelText(/코드/));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect((puts[0] as { blocked_types: string[] }).blocked_types.sort()).toEqual(["code", "http"]);
  });
});
