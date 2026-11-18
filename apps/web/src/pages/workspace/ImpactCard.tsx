// 후속(O2): 효과 리포트 — 앱마다 아낀 시간(추정)
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { formatMinutes, useImpact } from "@/lib/api/impact";

export function ImpactCard({ ws, range }: { ws: string; range?: { from?: string; to?: string } }) {
  const q = useImpact(ws, range);
  const d = q.data;
  return (
    <Card>
      <CardHeader
        title="아낀 시간(추정)"
        description="앱 설정 > 기능에서 '한 번 성공할 때 아끼는 시간'을 정하면, 성공한 실행 수를 곱해 보여 줘요. 시험·미리 보기·다시 실행은 세지 않아요."
      />
      <CardBody className="space-y-3">
        {q.isLoading && <Loading />}
        <ErrorBox error={q.error} />
        {d && (
          <>
            <p className="text-2xl font-semibold text-slate-900" data-testid="impact-total">
              {formatMinutes(d.total_saved_minutes)}
              <span className="ml-2 text-sm font-normal text-slate-500">
                성공한 실행 {d.total_succeeded_runs.toLocaleString()}건
              </span>
            </p>
            {d.unset_apps > 0 && (
              <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
                {d.unset_apps}개 앱은 &apos;아끼는 시간&apos;을 정하지 않아 계산에서 빠졌어요.
              </p>
            )}
            {d.apps.length === 0 ? (
              <p className="text-sm text-slate-500">아직 계산할 실행이 없어요.</p>
            ) : (
              <ul className="divide-y divide-slate-100 text-sm">
                {d.apps.slice(0, 8).map((a) => (
                  <li key={a.app_id} className="flex items-center justify-between gap-3 py-1.5">
                    <span className="min-w-0 truncate">{a.app_name}</span>
                    <span className="shrink-0 text-xs text-slate-500">
                      {a.succeeded_runs}건 ×{" "}
                      {a.minutes_per_run > 0 ? `${a.minutes_per_run}분` : "미설정"} ={" "}
                      <span className="font-medium text-slate-800">
                        {formatMinutes(a.saved_minutes)}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-[11px] text-slate-400">
              직접 잰 시간이 아니라 정해 둔 값으로 계산한 추정이에요.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  );
}
