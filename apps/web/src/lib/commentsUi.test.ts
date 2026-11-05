import type { Collaborator, CommentThread } from "@/lib/api/collab";
import {
  extractMentionIds,
  filterPeople,
  filterThreads,
  mentionQuery,
  openCountByNode,
  pickMention,
  pinThreads,
  timeAgo,
} from "@/lib/commentsUi";
import { editingHint } from "@/lib/presenceUi";

const people: Collaborator[] = [
  { id: "u1", name: "김오너", role: "owner" },
  { id: "u2", name: "김오너 부장", role: "admin" },
  { id: "u3", name: "이관리", role: "admin" },
  { id: "u4", name: "박빌더", role: "builder" },
];

function thread(over: Partial<CommentThread>): CommentThread {
  return {
    id: "t",
    node_id: null,
    x: null,
    y: null,
    parent_id: null,
    body: "본문",
    mentions: [],
    resolved: false,
    resolved_by: null,
    author: { id: "u1", name: "김오너" },
    created_at: "2026-11-05T00:00:00Z",
    edited_at: null,
    replies: [],
    ...over,
  };
}

test("@멘션 조각 찾기: 문장 앞·공백 뒤의 @만, 메일 주소는 제외", () => {
  expect(mentionQuery("안녕 @이", 5)).toEqual({ query: "이", start: 3 });
  expect(mentionQuery("@", 1)).toEqual({ query: "", start: 0 });
  expect(mentionQuery("a@b.com", 7)).toBeNull();
  expect(mentionQuery("안녕 @이관리 확인", 12)).toBeNull(); // 이미 공백이 지났다
  expect(mentionQuery("그냥 글", 3)).toBeNull();
});

test("멘션 고르기: 조각을 이름으로 바꾸고 캐럿을 이름 뒤로", () => {
  const r = pickMention("확인 @이", 5, "이관리");
  expect(r).toEqual({ text: "확인 @이관리 ", caret: 8 });
  const mid = pickMention("@박 뒤 글", 2, "박빌더");
  expect(mid?.text).toBe("@박빌더  뒤 글");
  expect(pickMention("글만", 2, "x")).toBeNull();
});

test("후보 거르기: 앞부분이 맞는 사람이 먼저, 공백은 무시", () => {
  expect(filterPeople(people, "김").map((p) => p.id)).toEqual(["u1", "u2"]);
  expect(filterPeople(people, "오너부장").map((p) => p.id)).toEqual(["u2"]);
  expect(filterPeople(people, "").length).toBe(4);
  expect(filterPeople(people, "리").map((p) => p.id)).toEqual(["u3"]);
  expect(filterPeople(people, "", 2)).toHaveLength(2);
});

test("본문에서 멘션한 사람 id: 긴 이름이 짧은 이름을 가로채지 않는다", () => {
  expect(extractMentionIds("@김오너 부장님 확인", people)).toEqual(["u2"]);
  expect(extractMentionIds("@김오너 와 @이관리 확인", people)).toEqual(["u1", "u3"]);
  expect(extractMentionIds("멘션 없음", people)).toEqual([]);
});

test("스레드 거르기·단계별 열린 댓글 수·캔버스 핀", () => {
  const ts = [
    thread({ id: "a", node_id: "n2" }),
    thread({ id: "b", node_id: "n2", resolved: true }),
    thread({ id: "c", node_id: "n3" }),
    thread({ id: "d", x: 10, y: 20 }),
    thread({ id: "e", x: 5, y: 5, resolved: true }),
  ];
  expect(filterThreads(ts, { status: "open" }).map((t) => t.id)).toEqual(["a", "c", "d"]);
  expect(filterThreads(ts, { status: "resolved" }).map((t) => t.id)).toEqual(["b", "e"]);
  expect(filterThreads(ts, { status: "all", nodeId: "n2" }).map((t) => t.id)).toEqual(["a", "b"]);
  expect(openCountByNode(ts)).toEqual({ n2: 1, n3: 1 });
  expect(pinThreads(ts).map((t) => t.id)).toEqual(["d"]);
});

test("시간 표시", () => {
  const now = new Date("2026-11-05T12:00:00Z").getTime();
  expect(timeAgo("2026-11-05T11:59:50Z", now)).toBe("방금");
  expect(timeAgo("2026-11-05T11:50:00Z", now)).toBe("10분 전");
  expect(timeAgo("2026-11-05T09:00:00Z", now)).toBe("3시간 전");
  expect(timeAgo("2026-11-03T12:00:00Z", now)).toBe("2일 전");
  expect(timeAgo("잘못된 값", now)).toBe("");
  // 시간대 표시가 없는 서버 시각은 UTC로 읽는다(한국 시간으로 읽으면 9시간 어긋난다)
  expect(timeAgo("2026-11-05T11:59:50", now)).toBe("방금");
  expect(timeAgo("2026-11-05T11:59:50.123456", now)).toBe("방금");
  expect(timeAgo("2026-11-05T20:50:00+09:00", now)).toBe("10분 전");
});

test("고치는 중 안내", () => {
  const u = (name: string, editing: boolean) => ({
    user_id: name,
    name,
    color: "#000",
    node_id: null,
    editing,
    can_edit: true,
  });
  expect(editingHint([u("가", false)])).toBe("");
  expect(editingHint([u("가", true)])).toBe("가님이 고치는 중");
  expect(editingHint([u("가", true), u("나", true), u("다", false)])).toBe(
    "가님 외 1명이 고치는 중",
  );
});
