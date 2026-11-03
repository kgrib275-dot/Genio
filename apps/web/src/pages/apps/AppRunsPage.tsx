import { Link, useParams } from "react-router-dom";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { StatusBadge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useApp, useAppRuns } from "@/lib/api/apps";
import type { Run } from "@/lib/api/types";
import { formatCost, formatDate } from "@/lib/cn";
import { AppNav } from "@/pages/apps/AppNav";

const TRIGGER: Record<string, string> = {
  test: "테스트",
  chat: "챗",
  api: "API",
  schedule: "예약",
};

export function RunTable({ runs, showApp }: { runs: Run[]; showApp?: boolean }) {
  if (runs.length === 0)
    return <p className="px-5 py-6 text-sm text-slate-500">아직 실행 기록이 없어요.</p>;
  return (
    <table className="w-full text-sm">
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
  );
}

export default function AppRunsPage() {
  const { id: appId = "" } = useParams();
  const app = useApp(appId);
  const runs = useAppRuns(appId);
  return (
    <div>
      <AppNav appId={appId} title={app.data?.name ?? ""} icon={app.data?.icon} />
      <div className="mx-auto max-w-6xl px-8 py-6">
        <ErrorBox error={app.error ?? runs.error} />
        {runs.isLoading && <Loading />}
        {runs.data && (
          <Card className="overflow-hidden">
            <RunTable runs={runs.data} />
          </Card>
        )}
      </div>
    </div>
  );
}
