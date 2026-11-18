import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SkillsCard } from "@/pages/workspace/SkillsCard";

const posts: unknown[] = [];

vi.mock("@/lib/api/client", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      get: async () => ({
        max_skills: 50,
        skills: [
          { id: "s1", name: "환불 안내", description: "환불을 물을 때 따를 순서", size: 120 },
        ],
      }),
      post: async (_p: string, body: unknown) => {
        posts.push(body);
        return { id: "s2", name: "x", description: "d", size: 1, body: "b" };
      },
    },
  };
});

function renderCard() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <SkillsCard ws="w1" />
    </QueryClientProvider>,
  );
}

describe("SkillsCard", () => {
  it("저장된 요령의 이름·설명을 보여 준다", async () => {
    renderCard();
    expect(await screen.findByText("환불 안내")).toBeInTheDocument();
    expect(screen.getByText("환불을 물을 때 따를 순서")).toBeInTheDocument();
  });

  it("이름·언제 쓰나요·내용을 모두 채워야 저장할 수 있다", async () => {
    posts.length = 0;
    renderCard();
    const save = screen.getByRole("button", { name: "저장" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("요령 이름"), { target: { value: "배송 안내" } });
    fireEvent.change(screen.getByLabelText("언제 쓰나요"), { target: { value: "배송을 물을 때" } });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("따를 내용"), {
      target: { value: "1. 송장 번호 확인" },
    });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({
      name: "배송 안내",
      description: "배송을 물을 때",
      body: "1. 송장 번호 확인",
    });
  });

  it("SKILL.md 붙여 넣기는 접어 둔 곳에서 쓴다", async () => {
    posts.length = 0;
    renderCard();
    fireEvent.change(screen.getByLabelText("SKILL.md 붙여 넣기"), {
      target: { value: "---\nname: A\ndescription: d\n---\n본문" },
    });
    fireEvent.click(screen.getByRole("button", { name: "붙여 넣은 내용으로 저장" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect((posts[0] as { skill_md: string }).skill_md).toContain("name: A");
  });
});
