// 활동 기록을 '지난 N일 한 줄 요약'으로 줄인다(AI 없이, 기록의 종류를 세어서 만든다).
import type { AuditLog } from "@/lib/api/types";

/** 눈여겨볼 변경(권한·비밀·삭제처럼 나중에 되짚을 일이 많은 것) */
export const NOTABLE = new Set([
  "member.role_change",
  "member.remove",
  "member.password_reset",
  "workspace.transfer_ownership",
  "workspace.security",
  "support.access",
  "workspace.export",
  "credential.delete",
  "llm_provider.create",
  "llm_provider.delete",
  "api_key.create",
  "app.delete",
  "kb.delete",
  "system.update",
]);

export interface AuditDigest {
  total: number;
  top: { action: string; count: number }[];
  people: { name: string; count: number }[];
  notable: { action: string; count: number }[];
}

export function summarizeAudit(
  logs: AuditLog[],
  days: number,
  nameOf: (l: AuditLog) => string,
  now = Date.now(),
): AuditDigest {
  const from = now - days * 86_400_000;
  const recent = logs.filter((l) => new Date(l.created_at).getTime() >= from);
  const count = <K extends string>(keys: K[]) => {
    const m = new Map<K, number>();
    for (const k of keys) m.set(k, (m.get(k) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  };
  return {
    total: recent.length,
    top: count(recent.map((l) => l.action))
      .slice(0, 4)
      .map(([action, c]) => ({ action, count: c })),
    people: count(recent.map(nameOf))
      .slice(0, 3)
      .map(([name, c]) => ({ name, count: c })),
    notable: count(recent.filter((l) => NOTABLE.has(l.action)).map((l) => l.action)).map(
      ([action, c]) => ({ action, count: c }),
    ),
  };
}
