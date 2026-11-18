import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { LlmSection } from "@/pages/workspace/sections";

const posts: string[] = [];
let providers: unknown[] = [];

vi.mock("@/lib/api/client", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      get: async (path: string) => {
        if (path.endsWith("/llm-providers")) return providers;
        return [];
      },
      post: async (path: string) => {
        posts.push(path);
        providers = [
          {
            id: "p1",
            provider: "demo",
            label: "데모 AI",
            default_model: "demo-1",
            is_default: true,
            api_key_masked: "****",
            base_url: null,
          },
        ];
        return { created: true, provider_id: "p1" };
      },
    },
  };
});

function renderSection() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <LlmSection ws="w1" manage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("데모 AI", () => {
  it("연결이 없으면 '키 없이 데모 AI로 체험하기'로 켜고, 켜면 데모 안내가 보인다", async () => {
    providers = [];
    renderSection();
    fireEvent.click(await screen.findByRole("button", { name: "키 없이 데모 AI로 체험하기" }));
    await waitFor(() => expect(posts).toEqual(["/workspaces/w1/llm-providers/demo"]));
    expect(await screen.findByTestId("demo-banner")).toHaveTextContent("지금은 데모 AI예요");
    expect(screen.getByText("데모 AI")).toBeInTheDocument();
  });
});
