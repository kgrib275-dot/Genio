import { Activity, Coins, Gauge, MessagesSquare, Smile, Timer } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { BarChart, ChartCard, LineChart, StatTile } from "@/components/charts";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { useApp } from "@/lib/api/apps";
import type { StatPoint } from "@/lib/api/types";
import { useAppStats } from "@/lib/api/v2";
import { cn, formatCost } from "@/lib/cn";
import { AppNav } from "@/pages/apps/AppNav";

const RANGES = [7, 14, 30];

function satisfaction(p: Pick<StatPoint, "likes" | "dislikes">): number | null {
  const total = p.likes + p.dislikes;
  return total ? p.likes / total : null;
}

function pct(v: number | null): string {
  return v === null ? "-" : `${Math.round(v * 100)}%`;
}

function ms(v: number): string {
  return v >= 1000 ? `${(v / 1000).toFixed(1)}초` : `${Math.round(v)}ms`;
}

export default function AppMonitorPage() {
  const { id: appId = "" } = useParams();
  const app = useApp(appId);
  const [days, setDays] = useState(7);
  const stats = useAppStats(appId, days);
  const d = stats.data;
  const series = (pick: (p: StatPoint) => number) =>
    (d?.days ?? []).map((p) => ({ label: p.date, value: pick(p) }));

  return (
    <div className="flex min-h-full flex-col">
      <AppNav appId={appId} title={app.data?.name ?? ""} icon={app.data?.icon} help="monitor" />
      <div className="mx-auto w-full max-w-6xl space-y-5 px-4 py-6 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-bold tracking-tight">모니터링</h2>
          <div className="inline-flex rounded-lg bg-slate-100 p-1" role="group" aria-label="기간">
            {RANGES.map((r) => (
              <button
                key={r}
                type="button"
                aria-pressed={days === r}
                onClick={() => setDays(r)}
                className={cn(
                  "rounded-md px-3 py-1 text-xs font-medium",
                  days === r ? "bg-white text-slate-900 shadow-sm" : "text-slate-500",
                )}
              >
                최근 {r}일
              </button>
            ))}
          </div>
        </div>
        {stats.isLoading && <Loading />}
        <ErrorBox error={stats.error} />
        {d && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
              <StatTile
                icon={<Activity className="h-3.5 w-3.5" />}
                label="실행"
                value={d.totals.runs.toLocaleString()}
              />
              <StatTile
                icon={<MessagesSquare className="h-3.5 w-3.5" />}
                label="대화"
                value={d.totals.conversations.toLocaleString()}
                sub={`메시지 ${d.totals.messages.toLocaleString()}`}
              />
              <StatTile
                icon={<Gauge className="h-3.5 w-3.5" />}
                label="토큰"
                value={(d.totals.input_tokens + d.totals.output_tokens).toLocaleString()}
                sub={`입력 ${d.totals.input_tokens.toLocaleString()} · 출력 ${d.totals.output_tokens.toLocaleString()}`}
              />
              <StatTile
                icon={<Coins className="h-3.5 w-3.5" />}
                label="비용"
                value={formatCost(d.totals.cost)}
              />
              <StatTile
                icon={<Timer className="h-3.5 w-3.5" />}
                label="평균 응답 시간"
                value={ms(d.totals.avg_latency_ms)}
                sub={`성공률 ${pct(d.totals.success_rate)}`}
              />
              <StatTile
                icon={<Smile className="h-3.5 w-3.5" />}
                label="만족도"
                value={pct(satisfaction(d.totals))}
                sub={`👍 ${d.totals.likes} · 👎 ${d.totals.dislikes}`}
              />
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              <ChartCard title="실행 수">
                <BarChart data={series((p) => p.runs)} />
              </ChartCard>
              <ChartCard title="대화 수">
                <BarChart data={series((p) => p.conversations)} tone="sky" />
              </ChartCard>
              <ChartCard title="토큰">
                <BarChart data={series((p) => p.input_tokens + p.output_tokens)} tone="amber" />
              </ChartCard>
              <ChartCard title="비용">
                <BarChart
                  data={series((p) => Number(p.cost) || 0)}
                  tone="rose"
                  format={(v) => formatCost(v)}
                />
              </ChartCard>
              <ChartCard title="평균 응답 시간">
                <LineChart data={series((p) => p.avg_latency_ms)} format={ms} />
              </ChartCard>
              <ChartCard title="성공률">
                <LineChart data={series((p) => p.success_rate)} max={1} format={(v) => pct(v)} />
              </ChartCard>
              <ChartCard title="만족도">
                <LineChart
                  data={series((p) => satisfaction(p) ?? 0)}
                  max={1}
                  format={(v) => pct(v)}
                />
              </ChartCard>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
