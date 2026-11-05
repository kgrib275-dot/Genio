// 접속 표시(v0.9) 안내 글.
import type { PresenceUser } from "@/lib/api/collab";

/** 고치는 중인 사람 안내 글: 한 명이면 '○○님이', 여럿이면 '○○님 외 n명이'. */
export function editingHint(others: PresenceUser[]): string {
  const editing = others.filter((u) => u.editing);
  const first = editing[0];
  if (!first) return "";
  return editing.length === 1
    ? `${first.name}님이 고치는 중`
    : `${first.name}님 외 ${editing.length - 1}명이 고치는 중`;
}
