// 캔버스 댓글(v0.9)의 순수 함수: @멘션 입력, 스레드 거르기, 단계별 개수, 시간 표시.
import type { Collaborator, CommentThread } from "@/lib/api/collab";

export type StatusFilter = "open" | "resolved" | "all";

/** 캐럿 바로 앞의 '@이름' 조각. 공백이 나오기 전까지만 이름으로 본다. */
export function mentionQuery(text: string, caret: number): { query: string; start: number } | null {
  const before = text.slice(0, caret);
  const at = before.lastIndexOf("@");
  if (at < 0) return null;
  if (at > 0 && !/\s/.test(before[at - 1] ?? "")) return null; // 메일 주소 같은 건 제외
  const query = before.slice(at + 1);
  if (/\s/.test(query)) return null;
  return { query, start: at };
}

/** 고른 이름으로 '@조각'을 바꾸고 새 캐럿 위치를 돌려준다. */
export function pickMention(
  text: string,
  caret: number,
  name: string,
): { text: string; caret: number } | null {
  const q = mentionQuery(text, caret);
  if (!q) return null;
  const insert = `@${name} `;
  return {
    text: text.slice(0, q.start) + insert + text.slice(caret),
    caret: q.start + insert.length,
  };
}

/** 입력 후보: 이름(공백 무시)에 검색어가 들어 있는 사람, 앞부분이 맞는 사람을 먼저. */
export function filterPeople(people: Collaborator[], query: string, limit = 6): Collaborator[] {
  const q = query.replace(/\s/g, "").toLowerCase();
  const norm = (s: string) => s.replace(/\s/g, "").toLowerCase();
  const hits = people.filter((p) => norm(p.name).includes(q));
  hits.sort((a, b) => Number(!norm(a.name).startsWith(q)) - Number(!norm(b.name).startsWith(q)));
  return hits.slice(0, limit);
}

/** 본문에 '@이름'이 들어 있는 사람의 id(긴 이름부터 맞춰서 앞부분이 같은 이름과 헷갈리지 않게). */
export function extractMentionIds(text: string, people: Collaborator[]): string[] {
  const out: string[] = [];
  let rest = text;
  for (const p of [...people].sort((a, b) => b.name.length - a.name.length)) {
    const tag = `@${p.name}`;
    if (rest.includes(tag) && !out.includes(p.id)) {
      out.push(p.id);
      rest = rest.split(tag).join(" ");
    }
  }
  return out;
}

export function filterThreads(
  threads: CommentThread[],
  opts: { status: StatusFilter; nodeId?: string | null },
): CommentThread[] {
  return threads.filter((t) => {
    if (opts.status === "open" && t.resolved) return false;
    if (opts.status === "resolved" && !t.resolved) return false;
    if (opts.nodeId && t.node_id !== opts.nodeId) return false;
    return true;
  });
}

/** 단계마다 '열려 있는' 댓글 수(캔버스 단계의 말풍선 숫자). */
export function openCountByNode(threads: CommentThread[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const t of threads) {
    if (t.resolved || !t.node_id) continue;
    out[t.node_id] = (out[t.node_id] ?? 0) + 1;
  }
  return out;
}

/** 캔버스 빈 곳에 꽂은 핀(단계에 달지 않고 위치만 있는 열린 댓글). */
export function pinThreads(threads: CommentThread[]): CommentThread[] {
  return threads.filter((t) => !t.node_id && t.x !== null && t.y !== null && !t.resolved);
}

/** 서버 시각 글자를 읽는다. 시간대 표시가 없으면 UTC로 본다(그대로 읽으면 한국 시간으로 9시간 어긋난다). */
export function parseServerTime(iso: string): number {
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(iso);
  return new Date(hasZone || !iso.includes("T") ? iso : `${iso}Z`).getTime();
}

export function timeAgo(iso: string, now: number = Date.now()): string {
  const t = parseServerTime(iso);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.floor((now - t) / 1000));
  if (s < 45) return "방금";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}분 전`;
  if (s < 86400) return `${Math.round(s / 3600)}시간 전`;
  if (s < 86400 * 7) return `${Math.round(s / 86400)}일 전`;
  return new Date(t).toLocaleDateString("ko-KR");
}
