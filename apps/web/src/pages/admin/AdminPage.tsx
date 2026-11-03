import { AppWindow, BookOpen, FileText, Globe, KeyRound, Shield, Users } from "lucide-react";
import { useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { AppIcon } from "@/components/AppIcon";
import { BarChart, ChartCard, LineChart, StatTile } from "@/components/charts";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Card, CardBody, CardHeader, PageHeader } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { HelpButton } from "@/help/HelpButton";
import type { AdminOverview } from "@/lib/api/types";
import { useAdminOverview } from "@/lib/api/v2";
import { useBuilderMetrics } from "@/lib/api/v5c";
import { formatCost } from "@/lib/cn";
import {
  AdminApiKeysSection,
  AuditSection,
  LlmSection,
  MembersSection,
  SystemSection,
  UsageSection,
} from "@/pages/workspace/sections";
import { TracingSection } from "@/pages/admin/TracingSection";
import { canManage, useSession } from "@/store/session";

type Tab = "overview" | "members" | "llm" | "usage" | "audit" | "keys" | "tracing" | "system";

const TABS: { value: Tab; label: string }[] = [
  { value: "overview", label: "개요" },
  { value: "members", label: "멤버" },
  { value: "llm", label: "AI 모델" },
  { value: "usage", label: "사용량" },
  { value: "audit", label: "활동 기록" },
  { value: "keys", label: "API 키" },
  { value: "tracing", label: "외부 추적" },
  { value: "system", label: "시스템 설정" },
];

function Overview({ ws }: { ws: string }) {
  const ov = useAdminOverview(ws, 14);
  if (ov.isLoading) return <Loading />;
  if (ov.error) return <ErrorBox error={ov.error} />;
  const d = ov.data;
  if (!d) return null;
  const c = d.counts;
  const series = (pick: (p: AdminOverview["days"][number]) => number) =>
    d.days.map((p) => ({ label: p.date, value: pick(p) }));
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile icon={<Users className="h-3.5 w-3.5" />} label="멤버" value={c.members} />
        <StatTile icon={<AppWindow className="h-3.5 w-3.5" />} label="앱" value={c.apps} />
        <StatTile
          icon={<Globe className="h-3.5 w-3.5" />}
          label="배포된 앱"
          value={c.published_apps}
        />
        <StatTile
          icon={<BookOpen className="h-3.5 w-3.5" />}
          label="지식베이스"
          value={c.knowledge_bases}
        />
        <StatTile icon={<FileText className="h-3.5 w-3.5" />} label="문서" value={c.documents} />
        <StatTile icon={<KeyRound className="h-3.5 w-3.5" />} label="API 키" value={c.api_keys} />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <ChartCard
          title="실행 수(최근 14일)"
          value={series((p) => p.runs)
            .reduce((a, b) => a + b.value, 0)
            .toLocaleString()}
        >
          <BarChart data={series((p) => p.runs)} />
        </ChartCard>
        <ChartCard
          title="비용"
          value={formatCost(d.days.reduce((a, p) => a + (Number(p.cost) || 0), 0))}
        >
          <BarChart
            data={series((p) => Number(p.cost) || 0)}
            tone="rose"
            format={(v) => formatCost(v)}
          />
        </ChartCard>
        <ChartCard title="토큰">
          <BarChart data={series((p) => p.tokens)} tone="amber" />
        </ChartCard>
        <ChartCard title="활동한 사람 · 대화">
          <LineChart data={series((p) => p.active_users)} />
          <p className="mt-2 text-xs text-slate-400">
            대화 {d.days.reduce((a, p) => a + p.conversations, 0).toLocaleString()}건
          </p>
        </ChartCard>
      </div>
      <Card>
        <CardHeader title="많이 쓰는 앱" />
        <CardBody className="p-0">
          {d.top_apps.length === 0 ? (
            <p className="px-5 pb-5 text-sm text-slate-500">아직 실행된 앱이 없어요.</p>
          ) : (
            <ul className="divide-y divide-slate-100 border-t border-slate-100">
              {d.top_apps.map((a) => (
                <li key={a.app_id}>
                  <Link
                    to={`/apps/${a.app_id}/monitor`}
                    className="flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-slate-50 sm:px-5"
                  >
                    <AppIcon name={a.app_name} size="sm" />
                    <span className="min-w-0 flex-1 truncate font-medium">{a.app_name}</span>
                    <span className="text-xs text-slate-500">실행 {a.runs.toLocaleString()}</span>
                    <span className="w-20 text-right text-xs text-slate-500">
                      {formatCost(a.cost)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
      <BuilderMetricsCard ws={ws} />
    </div>
  );
}

function seconds(v: number | null): string {
  if (v === null) return "-";
  if (v < 60) return `${Math.round(v)}초`;
  return `${Math.floor(v / 60)}분 ${Math.round(v % 60)}초`;
}

function percent(v: number | null): string {
  return v === null ? "-" : `${Math.round(v * 100)}%`;
}

/** 대화형 빌더 지표(기능 정의서 S1) */
function BuilderMetricsCard({ ws }: { ws: string }) {
  const m = useBuilderMetrics(ws);
  if (m.isLoading) return <Loading />;
  if (m.error) return <ErrorBox error={m.error} />;
  const d = m.data;
  if (!d) return null;
  return (
    <Card>
      <CardHeader
        title="빌더 지표"
        description="말로 만들기가 얼마나 잘 되는지 봐요. 첫 요청부터 검사를 통과한 앱까지 걸린 시간, 그 뒤 고쳐 달라고 한 횟수, 사람이 캔버스를 직접 고친 비율이에요."
      />
      <CardBody className="space-y-4">
        {d.sessions === 0 ? (
          <p className="text-sm text-slate-500">아직 빌더와 나눈 대화가 없어요.</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <StatTile
                label="빌더 대화"
                value={d.sessions}
                sub={`검사 통과 ${d.sessions_valid}`}
              />
              <StatTile
                label="동작하는 앱까지"
                value={seconds(d.avg_seconds_to_valid)}
                sub="평균"
              />
              <StatTile
                label="수정 대화"
                value={d.avg_edit_turns === null ? "-" : `${d.avg_edit_turns}번`}
                sub="검사 통과 뒤 평균"
              />
              <StatTile
                label="캔버스 직접 편집"
                value={percent(d.manual_ratio)}
                sub="낮을수록 말로 다 됨"
              />
            </div>
            {d.apps.length > 0 && (
              <ul className="divide-y divide-slate-100 rounded-lg border border-slate-100 text-sm">
                {d.apps.slice(0, 8).map((a) => (
                  <li
                    key={a.app_id}
                    className="flex flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-2"
                  >
                    <Link
                      to={`/apps/${a.app_id}/builder`}
                      className="min-w-0 flex-1 truncate font-medium hover:underline"
                    >
                      {a.app_name}
                    </Link>
                    <span className="text-xs text-slate-500">대화 {a.user_turns}번</span>
                    <span className="text-xs text-slate-500">
                      통과까지 {seconds(a.seconds_to_valid)}
                    </span>
                    <span className="text-xs text-slate-500">
                      직접 편집 {percent(a.manual_ratio)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}

/** 관리 콘솔(소유자·관리자 전용) */
export default function AdminPage() {
  const { workspaceId: ws, role } = useSession();
  const [params, setParams] = useSearchParams();
  const initial = (params.get("tab") as Tab | null) ?? "overview";
  const [tab, setTabState] = useState<Tab>(
    TABS.some((t) => t.value === initial) ? initial : "overview",
  );
  const setTab = (t: Tab) => {
    setTabState(t);
    setParams(t === "overview" ? {} : { tab: t }, { replace: true });
  };

  if (role && !canManage(role)) return <Navigate to="/workspace" replace />;

  return (
    <PageContainer>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <Shield className="h-6 w-6 text-indigo-500" /> 관리
          </span>
        }
        description="소유자·관리자만 보는 화면이에요. 워크스페이스 전체를 관리해요."
        help={<HelpButton page="admin" />}
      />
      <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <Tabs value={tab} onChange={setTab} items={TABS} />
      </div>
      {tab === "overview" && <Overview ws={ws} />}
      {tab === "members" && <MembersSection ws={ws} manage />}
      {tab === "llm" && <LlmSection ws={ws} manage showDefaults />}
      {tab === "usage" && <UsageSection ws={ws} />}
      {tab === "audit" && <AuditSection ws={ws} />}
      {tab === "keys" && <AdminApiKeysSection ws={ws} />}
      {tab === "tracing" && <TracingSection ws={ws} />}
      {tab === "system" && <SystemSection ws={ws} />}
    </PageContainer>
  );
}
