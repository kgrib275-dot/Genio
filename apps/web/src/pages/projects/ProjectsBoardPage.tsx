import {
  Activity,
  AlertTriangle,
  AppWindow,
  ArrowRight,
  CheckCircle2,
  Clock,
  Coins,
  FolderOpen,
  Gauge,
  Lock,
  Users,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { StatTile } from "@/components/charts";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { ProjectDot } from "@/components/projects/ProjectDialog";
import { Card, PageHeader } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { HelpButton } from "@/help/HelpButton";
import type { Project, ProjectStats } from "@/lib/api/types";
import { useProjectsOverview } from "@/lib/api/v3";
import { cn, formatCost, timeAgo } from "@/lib/cn";
import { useListControls } from "@/lib/useListControls";
import { canViewRuns, useSession } from "@/store/session";

type Days = "7" | "30" | "90";
type Sort = "runs" | "recent" | "cost" | "name";

const PERIODS: { value: Days; label: string }[] = [
  { value: "7", label: "7일" },
  { value: "30", label: "30일" },
  { value: "90", label: "90일" },
];

const SORTS: { value: Sort; label: string }[] = [
  { value: "runs", label: "실행 많은 순" },
  { value: "recent", label: "최근 활동 순" },
  { value: "cost", label: "비용 많은 순" },
  { value: "name", label: "이름 순" },
];

const STROKE: Record<string, string> = {
  indigo: "stroke-indigo-500",
  sky: "stroke-sky-500",
  emerald: "stroke-emerald-500",
  amber: "stroke-amber-500",
  rose: "stroke-rose-500",
  violet: "stroke-violet-500",
  slate: "stroke-slate-400",
};

function rate(v: number | null): string {
  return v === null ? "-" : `${Math.round(v * 100)}%`;
}

/** 실행 추이를 보여 주는 작은 선 그래프 */
function Sparkline({ data, color, label }: { data: number[]; color: string; label: string }) {
  const w = 160;
  const h = 36;
  const max = Math.max(1, ...data);
  const n = data.length;
  const pts = data.map((v, i) => {
    const x = n > 1 ? (i / (n - 1)) * w : w / 2;
    const y = h - 2 - (v / max) * (h - 6);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
      className="h-9 w-full"
    >
      <line x1="0" x2={w} y1={h - 1} y2={h - 1} className="stroke-slate-200" strokeWidth="1" />
      <polyline
        points={pts.join(" ")}
        fill="none"
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
        className={STROKE[color] ?? "stroke-indigo-500"}
      />
    </svg>
  );
}

function Metric({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] text-slate-500">{label}</p>
      <p
        className={cn(
          "truncate text-sm font-semibold tabular-nums",
          warn ? "text-red-600" : "text-slate-900",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function ProjectCard({
  project,
  stats,
  days,
}: {
  project: Project | null;
  stats: ProjectStats;
  days: number;
}) {
  const href = project ? `/?project=${project.id}` : "/?project=none";
  const name = project ? project.name : "프로젝트 없음(공용)";
  const failRate = stats.runs > 0 ? stats.failed / stats.runs : 0;
  const warn = stats.failed > 0 && failRate >= 0.2;
  return (
    <Card className="flex flex-col p-4" data-testid="project-card">
      <div className="flex items-start gap-2.5">
        {project ? (
          <ProjectDot color={project.color} className="mt-1.5 h-3 w-3" />
        ) : (
          <FolderOpen className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <h2 className="truncate text-[15px] font-bold text-slate-900">{name}</h2>
            {project?.visibility === "private" && (
              <Lock className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-label="비공개" />
            )}
          </div>
          <p className="mt-0.5 truncate text-xs text-slate-500">
            {stats.last_activity_at
              ? `마지막 활동 ${timeAgo(stats.last_activity_at)}`
              : "아직 활동이 없어요"}
            {project && ` · 만든 사람 ${project.created_by_name}`}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {stats.waiting_approval > 0 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
              <Clock className="h-3 w-3" /> 승인 대기 {stats.waiting_approval}
            </span>
          )}
          {warn && (
            <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-700">
              <AlertTriangle className="h-3 w-3" /> 실패 많음
            </span>
          )}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-3">
        <Metric label="앱(배포)" value={`${stats.apps} (${stats.published_apps})`} />
        <Metric label="지식(문서)" value={`${stats.knowledge_bases} (${stats.documents})`} />
        <Metric label="대화" value={stats.conversations.toLocaleString()} />
        <Metric label="실행" value={stats.runs.toLocaleString()} />
        <Metric label="성공률" value={rate(stats.success_rate)} warn={warn} />
        <Metric label="비용" value={formatCost(stats.cost)} />
      </div>

      <div className="mt-3">
        {stats.runs > 0 ? (
          <Sparkline
            data={stats.series.map((p) => p.runs)}
            color={project?.color ?? "slate"}
            label={`${name} 최근 ${days}일 실행 추이`}
          />
        ) : (
          <div className="flex h-9 items-end">
            <div className="w-full border-b border-dashed border-slate-200" />
          </div>
        )}
        <p className="mt-0.5 text-[10px] text-slate-400">
          {stats.runs > 0 ? `최근 ${days}일 실행 추이` : `최근 ${days}일 동안 실행이 없어요`}
        </p>
      </div>

      <div className="mt-auto flex items-center justify-between gap-2 border-t border-slate-100 pt-3">
        <span className="flex min-w-0 items-center gap-1 truncate text-xs text-slate-500">
          {project ? (
            <>
              <Users className="h-3.5 w-3.5 shrink-0" />
              {project.visibility !== "private"
                ? "워크스페이스 전체"
                : project.members.length > 0
                  ? `비공개 · 구성원 ${project.members.length}명`
                  : "비공개 · 만든 사람만"}
            </>
          ) : (
            "어느 프로젝트에도 속하지 않은 앱·지식"
          )}
        </span>
        <Link
          to={href}
          className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-700"
        >
          앱 보기 <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </Card>
  );
}

/** 프로젝트 현황판: 볼 수 있는 모든 프로젝트를 한 화면에서 비교한다 */
export default function ProjectsBoardPage() {
  const { workspaceId: ws, role } = useSession();
  const [params, setParams] = useSearchParams();
  const daysParam = params.get("days");
  const days: Days = daysParam === "7" || daysParam === "90" ? daysParam : "30";
  const [sort, setSort] = useState<Sort>("runs");
  const allowed = canViewRuns(role);
  const ov = useProjectsOverview(ws, Number(days), allowed);

  const rows = useMemo(() => {
    const list = [...(ov.data?.projects ?? [])];
    const t = (s: string | null) => (s ? new Date(s).getTime() : 0);
    list.sort((a, b) => {
      if (sort === "name") return a.project.name.localeCompare(b.project.name, "ko");
      if (sort === "recent") return t(b.last_activity_at) - t(a.last_activity_at);
      if (sort === "cost") return b.cost - a.cost;
      return b.runs - a.runs;
    });
    return list;
  }, [ov.data, sort]);

  const c = useListControls(rows, {
    key: "projects-board",
    search: (r) =>
      `${r.project.name} ${r.project.description} ${r.project.created_by_name} ${r.project.members
        .map((m) => m.name)
        .join(" ")}`,
    filters: [
      {
        id: "visibility",
        label: "공개 범위",
        options: [
          { value: "workspace", label: "워크스페이스 전체" },
          { value: "private", label: "비공개" },
        ],
        match: (r, v) => r.project.visibility === v,
      },
      {
        id: "health",
        label: "상태",
        options: [
          { value: "active", label: "실행 있음" },
          { value: "idle", label: "실행 없음" },
          { value: "failing", label: "실패 많음" },
          { value: "waiting", label: "승인 대기 있음" },
        ],
        match: (r, v) =>
          v === "active"
            ? r.runs > 0
            : v === "idle"
              ? r.runs === 0
              : v === "failing"
                ? r.failed > 0 && r.failed / Math.max(1, r.runs) >= 0.2
                : r.waiting_approval > 0,
      },
    ],
  });

  if (role && !allowed) return <Navigate to="/" replace />;

  const setDays = (v: Days) => {
    const next = new URLSearchParams(params);
    if (v === "30") next.delete("days");
    else next.set("days", v);
    setParams(next, { replace: true });
  };

  const d = ov.data;
  const u = d?.unassigned;
  const showUnassigned = Boolean(u && (u.apps > 0 || u.knowledge_bases > 0 || u.runs > 0));

  return (
    <PageContainer>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <Gauge className="h-6 w-6 text-indigo-500" /> 프로젝트 현황
          </span>
        }
        description="내가 볼 수 있는 모든 프로젝트의 앱·실행·비용을 한눈에 비교해요."
        help={<HelpButton page="projects" />}
      />
      <div className="flex flex-wrap items-center justify-between gap-x-4">
        <Tabs value={days} onChange={setDays} items={PERIODS} />
        <label className="mb-5 flex items-center gap-2 text-sm text-slate-500">
          정렬
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as Sort)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-800 focus:border-indigo-500 focus:outline-none"
          >
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {ov.isLoading && <Loading />}
      {ov.error && <ErrorBox error={ov.error} />}
      {d && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <StatTile
              icon={<FolderOpen className="h-3.5 w-3.5" />}
              label="프로젝트"
              value={d.totals.projects}
            />
            <StatTile
              icon={<AppWindow className="h-3.5 w-3.5" />}
              label="앱"
              value={d.totals.apps}
              sub={`배포 ${d.totals.published_apps}개`}
            />
            <StatTile
              icon={<Activity className="h-3.5 w-3.5" />}
              label="실행"
              value={d.totals.runs.toLocaleString()}
              sub={`대화 ${d.totals.conversations.toLocaleString()}건`}
            />
            <StatTile
              icon={<CheckCircle2 className="h-3.5 w-3.5" />}
              label="성공률"
              value={rate(d.totals.success_rate)}
              sub={d.totals.failed > 0 ? `실패 ${d.totals.failed}건` : undefined}
            />
            <StatTile
              icon={<Clock className="h-3.5 w-3.5" />}
              label="승인 대기"
              value={d.totals.waiting_approval}
            />
            <StatTile
              icon={<Coins className="h-3.5 w-3.5" />}
              label="비용"
              value={formatCost(d.totals.cost)}
            />
          </div>

          {rows.length > 0 && (
            <ListToolbar c={c} placeholder="프로젝트 이름·설명·구성원으로 찾기" />
          )}
          <NoMatch c={c} />
          {rows.length === 0 && !showUnassigned ? (
            <Card className="flex flex-col items-center gap-2 p-10 text-center">
              <FolderOpen className="h-8 w-8 text-slate-300" />
              <p className="text-sm font-semibold text-slate-700">아직 프로젝트가 없어요</p>
              <p className="text-sm text-slate-500">
                왼쪽 메뉴의 <b>+ 새 프로젝트</b>로 앱과 지식을 묶어 보세요.
              </p>
            </Card>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {c.pageItems.map((r) => (
                <ProjectCard key={r.project.id} project={r.project} stats={r} days={d.days} />
              ))}
              {/* '프로젝트 없음' 카드는 검색·필터 없이 볼 때 마지막 페이지에만 */}
              {showUnassigned && u && !c.active && c.page === c.pages && (
                <ProjectCard project={null} stats={u} days={d.days} />
              )}
            </div>
          )}
          {rows.length > 0 && <ListPager c={c} />}
          <p className="text-xs text-slate-400">
            실행·대화·비용은 최근 {d.days}일 기준이에요. 비공개 프로젝트는 볼 수 있는 사람에게만
            보여요.
          </p>
        </div>
      )}
    </PageContainer>
  );
}
