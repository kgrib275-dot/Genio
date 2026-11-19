import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api/client";

export interface AppDigest {
  today: { succeeded: number; failed: number; total: number };
  week: { succeeded: number; failed: number; total: number };
  failure_reasons: { reason: string; count: number }[];
  headline: string;
}

export function useAppDigest(appId: string) {
  return useQuery({
    queryKey: ["app-digest", appId],
    queryFn: () => api.get<AppDigest>(`/apps/${appId}/digest`),
    enabled: Boolean(appId),
    refetchInterval: 60_000,
  });
}

/** 실행 현황 맨 위: 오늘 몇 건 처리했는지 한 줄과 실패 이유 */
export function DigestCard({ appId }: { appId: string }) {
  const q = useAppDigest(appId);
  const d = q.data;
  if (!d) return null;
  const bad = d.week.failed > 0;
  return (
    <Card className="flex flex-col gap-2 p-4 sm:flex-row sm:items-start sm:gap-4">
      {bad ? (
        <AlertTriangle className="h-6 w-6 shrink-0 text-amber-500" />
      ) : (
        <CheckCircle2 className="h-6 w-6 shrink-0 text-emerald-500" />
      )}
      <div className="min-w-0 flex-1">
        <p className="text-base font-semibold text-slate-900" data-testid="digest-headline">
          {d.headline}
        </p>
        <p className="text-sm text-slate-500">
          이번 주(7일): 성공 {d.week.succeeded}건 · 실패 {d.week.failed}건 · 시험 실행은 세지
          않아요.
        </p>
        {d.failure_reasons.length > 0 && (
          <ul className="mt-2 space-y-1 text-sm text-slate-700">
            {d.failure_reasons.map((r) => (
              <li key={r.reason} className="flex gap-2">
                <span className="shrink-0 rounded bg-amber-100 px-1.5 text-xs font-medium text-amber-800">
                  {r.count}건
                </span>
                <span className="min-w-0 break-words">{r.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
