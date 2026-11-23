// sections.tsx에서 분리한 구간: UsageSection
import { BarChart3 } from "lucide-react";
import { useState } from "react";
import { ActivationFunnel } from "@/components/onboarding/ActivationFunnel";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { StatTile } from "@/components/charts";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { useUsage } from "@/lib/api/workspace";
import { ImpactCard } from "@/pages/workspace/ImpactCard";
import { formatCost } from "@/lib/cn";
import { useListControls } from "@/lib/useListControls";
import { useSession } from "@/store/session";
import { CostEstimateCard, LimitsCard, UsageByUserList } from "@/pages/workspace/costSections";

// ---------------- 사용량 ----------------
export function UsageSection({ ws }: { ws: string }) {
  const role = useSession((st) => st.role);
  const [group, setGroup] = useState<"app" | "user">("app");
  const usage = useUsage(ws);
  const uc = useListControls(usage.data?.by_app, {
    key: "usage",
    search: (a) => a.app_name,
  });
  if (usage.isLoading) return <Loading />;
  if (usage.error) return <ErrorBox error={usage.error} />;
  const u = usage.data;
  if (!u) return null;
  return (
    <div className="space-y-6">
      {role === "admin" && <ActivationFunnel ws={ws} />}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="실행 수" value={u.total_runs.toLocaleString()} />
        <StatTile label="입력 토큰" value={u.total_input_tokens.toLocaleString()} />
        <StatTile label="출력 토큰" value={u.total_output_tokens.toLocaleString()} />
        <StatTile label="비용" value={formatCost(u.total_cost)} />
      </div>
      <div
        role="tablist"
        aria-label="사용량 보기"
        className="inline-flex rounded-lg bg-slate-100 p-1"
      >
        {(
          [
            ["app", "앱별"],
            ["user", "사람별"],
          ] as const
        ).map(([v, label]) => (
          <button
            key={v}
            type="button"
            role="tab"
            aria-selected={group === v}
            onClick={() => setGroup(v)}
            className={`rounded-md px-3 py-1 text-sm ${
              group === v ? "bg-white font-medium text-slate-900 shadow-sm" : "text-slate-500"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {group === "user" ? (
        <UsageByUserList ws={ws} />
      ) : u.by_app.length === 0 ? (
        <EmptyState
          icon={<BarChart3 className="h-5 w-5" />}
          title="아직 사용 기록이 없어요"
          description="AI를 쓰는 앱을 실행하면 앱별 호출 수·토큰·비용이 여기에 쌓여요."
          action={{ label: "앱 보러 가기", to: "/" }}
        />
      ) : (
        <div className="space-y-3">
          <ListToolbar c={uc} placeholder="앱 이름 검색" />
          <Card className="overflow-hidden">
            <div className="hidden grid-cols-[1fr_repeat(4,6rem)] gap-2 bg-slate-50 px-4 py-2 text-xs font-medium text-slate-500 md:grid">
              <span>앱</span>
              <span className="text-right">실행</span>
              <span className="text-right">AI가 읽은 양(토큰)</span>
              <span className="text-right">AI가 쓴 양(토큰)</span>
              <span className="text-right">비용</span>
            </div>
            <ul className="divide-y divide-slate-100">
              {uc.pageItems.map((a) => (
                <li
                  key={a.app_id}
                  className="grid grid-cols-2 gap-x-2 gap-y-0.5 px-4 py-2.5 text-sm md:grid-cols-[1fr_repeat(4,6rem)]"
                >
                  <span className="col-span-2 font-medium md:col-span-1">{a.app_name}</span>
                  <span className="text-xs text-slate-500 md:text-right md:text-sm md:text-slate-700">
                    <span className="md:hidden">실행 </span>
                    {a.runs}
                  </span>
                  <span className="text-xs text-slate-500 md:text-right md:text-sm md:text-slate-700">
                    <span className="md:hidden">입력 </span>
                    {a.input_tokens.toLocaleString()}
                  </span>
                  <span className="text-xs text-slate-500 md:text-right md:text-sm md:text-slate-700">
                    <span className="md:hidden">출력 </span>
                    {a.output_tokens.toLocaleString()}
                  </span>
                  <span className="text-xs text-slate-500 md:text-right md:text-sm md:text-slate-700">
                    <span className="md:hidden">비용 </span>
                    {formatCost(a.cost)}
                  </span>
                </li>
              ))}
            </ul>
            <NoMatch c={uc} />
          </Card>
          <ListPager c={uc} />
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        <ImpactCard ws={ws} />
        <CostEstimateCard ws={ws} />
        {(role === "owner" || role === "admin") && <LimitsCard ws={ws} />}
      </div>
    </div>
  );
}
