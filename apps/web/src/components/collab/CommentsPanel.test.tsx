import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { CommentsPanel } from "@/components/collab/CommentsPanel";
import type { Collaborator, CommentThread } from "@/lib/api/collab";
import { useCanvas } from "@/store/canvas";
import { useCollab } from "@/store/collab";

const people: Collaborator[] = [
  { id: "u-admin", name: "이관리", role: "admin" },
  { id: "u-me", name: "박빌더", role: "builder" },
];

function thread(over: Partial<CommentThread>): CommentThread {
  return {
    id: "t1",
    node_id: "n2",
    x: null,
    y: null,
    parent_id: null,
    body: "이 문구 확인해 주세요",
    mentions: [],
    resolved: false,
    resolved_by: null,
    author: { id: "u-admin", name: "이관리" },
    created_at: new Date().toISOString(),
    edited_at: null,
    replies: [],
    ...over,
  };
}

let threads: CommentThread[] = [];
const createMutate = vi.fn();
const resolveMutate = vi.fn();
vi.mock("@/lib/api/collab", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/collab")>("@/lib/api/collab");
  return {
    ...actual,
    useComments: () => ({ data: threads, isLoading: false }),
    useCollaborators: () => ({ data: people }),
    useCreateComment: () => ({ mutate: createMutate, isPending: false }),
    useEditComment: () => ({ mutate: vi.fn(), isPending: false }),
    useDeleteComment: () => ({ mutate: vi.fn(), isPending: false }),
    useResolveComment: () => ({ mutate: resolveMutate, isPending: false }),
  };
});

beforeEach(() => {
  createMutate.mockClear();
  resolveMutate.mockClear();
  useCollab.getState().start("app1", 1, "u-me");
  useCanvas.getState().load("app1", {
    version: 1,
    nodes: [
      { id: "n2", type: "template", position: { x: 0, y: 0 }, data: { label: "다듬기" } },
      { id: "n3", type: "output", position: { x: 0, y: 0 }, data: { label: "결과" } },
    ],
    edges: [],
    variables: {},
  });
  threads = [
    thread({ id: "t1", node_id: "n2" }),
    thread({
      id: "t2",
      node_id: "n3",
      body: "이미 끝난 일",
      resolved: true,
      resolved_by: "박빌더",
    }),
  ];
});

const panel = (canWrite = true) => (
  <CommentsPanel appId="app1" canWrite={canWrite} canDeleteAny={false} onClose={() => undefined} />
);

test("기본은 열린 댓글만, 해결·전체로 바꿔 볼 수 있다", () => {
  render(panel());
  expect(screen.getByText("이 문구 확인해 주세요")).toBeTruthy();
  expect(screen.queryByText("이미 끝난 일")).toBeNull();
  fireEvent.click(screen.getByRole("radio", { name: "해결" }));
  expect(screen.getByText("이미 끝난 일")).toBeTruthy();
  expect(screen.queryByText("이 문구 확인해 주세요")).toBeNull();
  fireEvent.click(screen.getByRole("radio", { name: "전체" }));
  expect(screen.getByText("이미 끝난 일")).toBeTruthy();
  expect(screen.getByText("이 문구 확인해 주세요")).toBeTruthy();
});

test("스레드에 단계 이름이 보이고, 해결 처리를 보낸다", () => {
  render(panel());
  expect(screen.getByText("다듬기")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /해결/ }));
  expect(resolveMutate).toHaveBeenCalledWith({ id: "t1", resolved: true }, expect.anything());
});

test("읽기만 하는 역할은 쓰기·해결 버튼이 없다", () => {
  render(panel(false));
  expect(screen.getByText("이 문구 확인해 주세요")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /해결/ })).toBeNull();
  expect(screen.queryByText("답글")).toBeNull();
  expect(screen.queryByRole("button", { name: /고른 단계에 댓글/ })).toBeNull();
});

test("고른 단계에 댓글: @로 사람을 부르면 멘션 id가 함께 간다", () => {
  useCanvas.getState().select("n3");
  useCollab.getState().openCompose({ nodeId: "n3", x: null, y: null });
  render(panel());
  expect(screen.getByText(/'결과' 단계에 댓글을 남겨요/)).toBeTruthy();
  const box = screen.getByRole("textbox", { name: "댓글 쓰기" }) as HTMLTextAreaElement;
  fireEvent.change(box, { target: { value: "@이", selectionStart: 2 } });
  fireEvent.select(box, { target: { selectionStart: 2 } });
  const option = screen.getByRole("option", { name: /이관리/ });
  fireEvent.mouseDown(option.querySelector("button") as HTMLElement);
  expect((screen.getByRole("textbox", { name: "댓글 쓰기" }) as HTMLTextAreaElement).value).toBe(
    "@이관리 ",
  );
  fireEvent.change(screen.getByRole("textbox", { name: "댓글 쓰기" }), {
    target: { value: "@이관리 확인 부탁해요", selectionStart: 14 },
  });
  fireEvent.click(screen.getByRole("button", { name: "남기기" }));
  expect(createMutate).toHaveBeenCalledTimes(1);
  const body = createMutate.mock.calls[0]?.[0] as Record<string, unknown>;
  expect(body.node_id).toBe("n3");
  expect(body.mentions).toEqual(["u-admin"]);
  expect(body.body).toBe("@이관리 확인 부탁해요");
});

test("빈 댓글은 보낼 수 없다", () => {
  useCollab.getState().openCompose({ nodeId: null, x: 40, y: 80 });
  render(panel());
  expect(screen.getByText(/캔버스 이 위치에 댓글을 남겨요/)).toBeTruthy();
  const send = screen.getByRole("button", { name: "남기기" }) as HTMLButtonElement;
  expect(send.disabled).toBe(true);
  fireEvent.change(screen.getByRole("textbox", { name: "댓글 쓰기" }), {
    target: { value: "   " },
  });
  expect(send.disabled).toBe(true);
});
