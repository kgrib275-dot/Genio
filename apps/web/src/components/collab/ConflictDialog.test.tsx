import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { ConflictDialog } from "@/components/collab/ConflictDialog";
import { PresenceBar } from "@/components/collab/PresenceBar";
import type { DraftConflict } from "@/lib/api/collab";
import { useCollab } from "@/store/collab";

const saveResolved = vi.fn(() => Promise.resolve());
const adoptTheirs = vi.fn();
vi.mock("@/lib/collabSave", () => ({
  saveResolved: (...a: unknown[]) => (saveResolved as (...x: unknown[]) => Promise<void>)(...a),
  adoptTheirs: (...a: unknown[]) => (adoptTheirs as (...x: unknown[]) => void)(...a),
  saveDraftNow: vi.fn(),
}));

const merged = {
  nodes: [
    { id: "n1", type: "input", data: {} },
    {
      id: "n2",
      type: "template",
      data: { label: "다듬기", template: "상대 글", prompt: "상대 지시" },
    },
  ],
  edges: [{ id: "e1", source: "n1", target: "n2" }],
  variables: {},
};

function conflict(over: Partial<DraftConflict> = {}): DraftConflict {
  return {
    rev: 7,
    stale: false,
    base: null,
    mine: {},
    theirs: {},
    merged,
    conflicts: [
      {
        kind: "node",
        node_id: "n2",
        field: "data.template",
        label: "다듬기",
        base: "원래",
        mine: "내 글",
        theirs: "상대 글",
      },
      {
        kind: "node",
        node_id: "n2",
        field: "data.prompt",
        label: "다듬기",
        base: "원래 지시",
        mine: "내 지시",
        theirs: "상대 지시",
      },
    ],
    ...over,
  };
}

beforeEach(() => {
  saveResolved.mockClear();
  adoptTheirs.mockClear();
  useCollab.getState().start("app1", 3, "u-me");
});

test("충돌이 없으면 아무것도 그리지 않는다", () => {
  const { container } = render(<ConflictDialog appId="app1" />);
  expect(container).toBeEmptyDOMElement();
});

test("항목마다 내 것·상대 것을 골라야 저장할 수 있고, 고른 대로 저장한다", async () => {
  useCollab.getState().setConflict(conflict());
  render(<ConflictDialog appId="app1" />);
  expect(screen.getByRole("dialog", { name: "충돌 해결" })).toBeTruthy();
  expect(screen.getByText("글 틀")).toBeTruthy();
  expect(screen.getByText("AI에게 줄 지시")).toBeTruthy();
  const save = screen.getByRole("button", { name: "고른 대로 저장" }) as HTMLButtonElement;
  expect(save.disabled).toBe(true);
  const mineRadios = screen.getAllByRole("radio", { name: /내 것/ });
  const theirsRadios = screen.getAllByRole("radio", { name: /상대 것/ });
  fireEvent.click(mineRadios[0] as HTMLElement); // 글 틀은 내 것
  expect(save.disabled).toBe(true); // 하나만 골랐다
  fireEvent.click(theirsRadios[1] as HTMLElement); // 지시는 상대 것
  expect(save.disabled).toBe(false);
  fireEvent.click(save);
  await waitFor(() => expect(saveResolved).toHaveBeenCalledTimes(1));
  const [appId, graph, rev] = saveResolved.mock.calls[0] as unknown as [
    string,
    { nodes: { id: string; data: Record<string, string> }[] },
    number,
  ];
  expect(appId).toBe("app1");
  expect(rev).toBe(7);
  const n2 = graph.nodes.find((n) => n.id === "n2");
  expect(n2?.data.template).toBe("내 글");
  expect(n2?.data.prompt).toBe("상대 지시");
});

test("'모두 내 것으로'는 한 번에 고른다", async () => {
  useCollab.getState().setConflict(conflict());
  render(<ConflictDialog appId="app1" />);
  fireEvent.click(screen.getByRole("button", { name: "모두 내 것으로" }));
  fireEvent.click(screen.getByRole("button", { name: "고른 대로 저장" }));
  await waitFor(() => expect(saveResolved).toHaveBeenCalled());
  const graph = (saveResolved.mock.calls[0] as unknown as [string, typeof merged])[1];
  expect(graph.nodes[1]?.data.template).toBe("내 글");
  expect(graph.nodes[1]?.data.prompt).toBe("내 지시");
});

test("너무 오래된 기준이면 '새로 불러오기'와 '덮어쓰기' 두 갈래", async () => {
  useCollab
    .getState()
    .setConflict(
      conflict({ stale: true, conflicts: [], mine: { nodes: [] }, theirs: { nodes: [1] } }),
    );
  render(<ConflictDialog appId="app1" />);
  expect(screen.getByText("흐름이 많이 바뀌었어요")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "상대가 저장한 흐름으로 새로 불러오기" }));
  expect(adoptTheirs).toHaveBeenCalledWith({ nodes: [1] }, 7);
  act(() =>
    useCollab
      .getState()
      .setConflict(conflict({ stale: true, conflicts: [], mine: { nodes: ["내 것"] } })),
  );
  fireEvent.click(await screen.findByRole("button", { name: "내 것으로 덮어쓰기" }));
  await waitFor(() => expect(saveResolved).toHaveBeenCalledWith("app1", { nodes: ["내 것"] }, 7));
});

test("접속 표시: 나는 빼고 다른 사람만, 고치는 중이면 안내", () => {
  const u = (id: string, name: string, editing: boolean) => ({
    user_id: id,
    name,
    color: "#6366f1",
    node_id: null,
    editing,
    can_edit: true,
  });
  useCollab.getState().setUsers([u("u-me", "나", true), u("u2", "이관리", true)]);
  render(<PresenceBar />);
  expect(screen.getByLabelText("같이 보고 있는 사람").children).toHaveLength(1);
  expect(screen.getByRole("status").textContent).toContain("이관리님이 고치는 중");
  act(() => useCollab.getState().setUsers([u("u-me", "나", false)]));
});
