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
import { formatCost } from "@/lib/cn";
import {
  AdminApiKeysSection,
  AuditSection,
  LlmSection,
  MembersSection,
  SystemSection,
  UsageSection,
} from "@/pages/workspace/sections";
import { canManage, useSession } from "@/store/session";

type Tab = "overview" | "members" | "llm" | "usage" | "audit" | "keys" | "system";

const TABS: { value: Tab; label: string }[] = [
  { value: "overview", label: "개요" },
  { value: "members", label: "멤버" },
  { value: "llm", label: "AI 모델" },
  { value: "usage", label: "사용량" },
  { value: "audit", label: "활동 기록" },
  { value: "keys", label: "API 키" },
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
    </div>
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
      {tab === "system" && <SystemSection ws={ws} />}
    </PageContainer>
  );
}
