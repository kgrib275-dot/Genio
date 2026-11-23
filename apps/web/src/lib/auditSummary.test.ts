import { describe, expect, it } from "vitest";
import type { AuditLog } from "@/lib/api/types";
import { summarizeAudit } from "./auditSummary";

const log = (action: string, who: string, daysAgo: number): AuditLog => ({
  id: Math.random().toString(),
  user_id: who,
  user_email: who,
  action,
  target_type: "x",
  target_id: null,
  meta: {},
  created_at: new Date(Date.now() - daysAgo * 86_400_000).toISOString(),
});

describe("summarizeAudit", () => {
  it("기간 안의 기록만 세고 눈여겨볼 변경을 따로 뽑는다", () => {
    const d = summarizeAudit(
      [
        log("app.create", "김", 1),
        log("app.create", "김", 2),
        log("member.role_change", "박", 3),
        log("app.create", "김", 20),
      ],
      7,
      (l) => l.user_email ?? "시스템",
    );
    expect(d.total).toBe(3);
    expect(d.top[0]).toEqual({ action: "app.create", count: 2 });
    expect(d.people[0]).toEqual({ name: "김", count: 2 });
    expect(d.notable).toEqual([{ action: "member.role_change", count: 1 }]);
  });
});
