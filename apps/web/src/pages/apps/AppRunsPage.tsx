import { Link, useParams } from "react-router-dom";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { StatusBadge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useApp, useAppRuns } from "@/lib/api/apps";
import type { Run } from "@/lib/api/types";
import { formatCost, formatDate } from "@/lib/cn";
import { RUN_FILTERS, runSearchText, TRIGGER } from "@/lib/runLabels";
import { useListControls } from "@/lib/useListControls";
import { AppNav } from "@/pages/apps/AppNav";
import { EmptyState } from "@/components/EmptyState";
import { PlayCircle } from "lucide-react";

export function RunTable({ runs, showApp }: { runs: Run[]; showApp?: boolean }) {
  if (runs.length === 0)
    return (
      <EmptyState
        compact
        icon={<PlayCircle className="h-5 w-5" />}
        title="아직 실행 기록이 없어요"
        description="만들기 화면의 '테스트 실행'이나 배포한 링크·자동 실행으로 앱이 돌면 결과가 여기에 쌓여요."
      />
    );
  return (
    <>
      {/* 좁은 화면: 표 대신 쌓인 카드 */}
      <ul className="divide-y divide-slate-100 md:hidden">
        {runs.map((r) => (
          <li key={r.id}>
            <Link to={`/runs/${r.id}`} className="block space-y-1 px-4 py-3 hover:bg-slate-50">
              <span className="flex items-center gap-2 text-sm">
                <StatusBadge status={r.status} />
                {showApp && <span className="truncate font-medium">{r.app_name ?? "-"}</span>}
                <span className="ml-auto text-xs text-slate-400">{formatDate(r.created_at)}</span>
              </span>
              <span className="block truncate text-xs text-slate-600">
                {r.error ?? r.output?.text ?? "-"}
              </span>
              <span className="block text-[11px] text-slate-400">
                {TRIGGER[r.trigger] ?? r.trigger} · 토큰{" "}
                {(r.token_usage?.input_tokens ?? 0) + (r.token_usage?.output_tokens ?? 0)} ·{" "}
                {formatCost(r.cost)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
      <table className="hidden w-full text-sm md:table">
        <thead className="bg-slate-50 text-left text-xs text-slate-500">
          <tr>
            <th className="px-4 py-2 font-medium">시작</th>
            {showApp && <th className="px-4 py-2 font-medium">앱</th>}
            <th className="px-4 py-2 font-medium">방식</th>
            <th className="px-4 py-2 font-medium">상태</th>
            <th className="px-4 py-2 font-medium">결과</th>
            <th className="px-4 py-2 text-right font-medium">토큰</th>
            <th className="px-4 py-2 text-right font-medium">비용</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {runs.map((r) => (
            <tr key={r.id} className="hover:bg-slate-50">
              <td className="whitespace-nowrap px-4 py-2">
                <Link className="text-indigo-600 hover:underline" to={`/runs/${r.id}`}>
                  {formatDate(r.created_at)}
                </Link>
              </td>
              {showApp && <td className="px-4 py-2">{r.app_name ?? "-"}</td>}
              <td className="px-4 py-2">{TRIGGER[r.trigger] ?? r.trigger}</td>
              <td className="px-4 py-2">
                <StatusBadge status={r.status} />
              </td>
              <td className="max-w-xs truncate px-4 py-2 text-slate-600">
                {r.error ?? r.output?.text ?? "-"}
              </td>
              <td className="px-4 py-2 text-right text-xs text-slate-500">
                {(r.token_usage?.input_tokens ?? 0) + (r.token_usage?.output_tokens ?? 0)}
              </td>
              <td className="px-4 py-2 text-right text-xs text-slate-500">{formatCost(r.cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function RunList({ runs }: { runs: Run[] }) {
  const c = useListControls(runs, {
    key: "app-runs",
    search: runSearchText,
    filters: RUN_FILTERS,
  });
  if (runs.length === 0)
    return (
      <Card className="overflow-hidden">
        <RunTable runs={[]} />
      </Card>
    );
  return (
    <div className="space-y-3">
      <ListToolbar c={c} placeholder="결과·오류 내용으로 찾기" />
      <Card className="overflow-hidden">
        {c.total > 0 ? <RunTable runs={c.pageItems} /> : <NoMatch c={c} />}
      </Card>
      <ListPager c={c} />
    </div>
  );
}

export default function AppRunsPage() {
  const { id: appId = "" } = useParams();
  const app = useApp(appId);
  const runs = useAppRuns(appId);
  return (
    <div>
      <AppNav appId={appId} title={app.data?.name ?? ""} icon={app.data?.icon} help="runs" />
      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-8">
        <ErrorBox error={app.error ?? runs.error} />
        {runs.isLoading && <Loading />}
        {runs.data && <RunList runs={runs.data} />}
      </div>
    </div>
  );
}
