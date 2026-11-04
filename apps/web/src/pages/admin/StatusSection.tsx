// 운영 준비: 관리 > 시스템 상태(인스턴스 관리자). 서버 각 부분의 상태와 최근 서버 오류 기록.
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  RefreshCw,
  Users,
  Workflow,
  XCircle,
} from "lucide-react";
import { useState } from "react";
import { StatTile } from "@/components/charts";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Empty } from "@/components/ui/card";
import {
  useServerErrors,
  useSystemStatus,
  type ErrorEvent,
  type HealthStatus,
} from "@/lib/api/ops";
import { cn, copyText, formatDate } from "@/lib/cn";
import { optionsFrom, useListControls } from "@/lib/useListControls";

const LOOK: Record<HealthStatus, { label: string; tone: "green" | "amber" | "red" | "gray" }> = {
  ok: { label: "정상", tone: "green" },
  warn: { label: "주의", tone: "amber" },
  error: { label: "문제", tone: "red" },
  unknown: { label: "확인 불가", tone: "gray" },
};

function StatusIcon({ s }: { s: HealthStatus }) {
  const cls = "h-5 w-5 shrink-0";
  if (s === "ok") return <CheckCircle2 className={cn(cls, "text-emerald-500")} />;
  if (s === "warn") return <AlertTriangle className={cn(cls, "text-amber-500")} />;
  if (s === "error") return <XCircle className={cn(cls, "text-red-500")} />;
  return <CircleHelp className={cn(cls, "text-slate-400")} />;
}

const SOURCE_LABELS: Record<string, string> = { api: "API", engine: "실행 엔진", worker: "워커" };

function ErrorsCard() {
  const errors = useServerErrors();
  const [open, setOpen] = useState<string | null>(null);
  const c = useListControls<ErrorEvent>(errors.data, {
    key: "server-errors",
    search: (e) => `${e.where} ${e.error_type} ${e.message} ${e.request_id ?? ""}`,
    filters: [
      {
        id: "source",
        label: "어디서",
        options: optionsFrom(
          errors.data,
          (e) => e.source,
          (s) => SOURCE_LABELS[s] ?? s,
        ),
        match: (e, v) => e.source === v,
      },
      {
        id: "type",
        label: "오류 종류",
        options: optionsFrom(errors.data, (e) => e.error_type),
        match: (e, v) => e.error_type === v,
      },
    ],
  });
  return (
    <Card>
      <CardHeader
        title="서버 오류 기록"
        description="처리하지 못한 서버 오류예요(30일 보관). 사용자가 알려 준 '문의 번호'로 찾을 수 있어요. 비밀값은 가려서 남겨요."
      />
      <CardBody className="p-0">
        {errors.isLoading && <Loading />}
        <ErrorBox error={errors.error} />
        {errors.data?.length === 0 && <Empty>최근 30일 동안 서버 오류가 없어요.</Empty>}
        {(errors.data?.length ?? 0) > 0 && (
          <ListToolbar c={c} placeholder="문의 번호·경로·내용 검색" className="px-4 pb-3 sm:px-5" />
        )}
        <NoMatch c={c} />
        <ul className="divide-y divide-slate-100 border-t border-slate-100 empty:hidden">
          {c.pageItems.map((e) => (
            <li key={e.id} className="px-4 py-3 text-sm sm:px-5">
              <button
                type="button"
                className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-left"
                onClick={() => setOpen((o) => (o === e.id ? null : e.id))}
                aria-expanded={open === e.id}
              >
                <span className="w-36 shrink-0 text-xs text-slate-500">
                  {formatDate(e.created_at)}
                </span>
                <Badge tone={e.source === "engine" ? "amber" : "red"}>
                  {SOURCE_LABELS[e.source] ?? e.source}
                </Badge>
                <span className="font-medium text-slate-800">{e.error_type || "오류"}</span>
                <span className="min-w-0 flex-1 truncate font-mono text-xs text-slate-500">
                  {e.where}
                </span>
              </button>
              {open === e.id && (
                <div className="mt-2 space-y-1.5 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-700">
                  <p className="whitespace-pre-wrap break-all">{e.message || "(내용 없음)"}</p>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-slate-500">
                    {e.request_id && (
                      <span>
                        문의 번호 <code className="font-mono">{e.request_id}</code>{" "}
                        <button
                          type="button"
                          className="text-indigo-600 hover:underline"
                          onClick={() => void copyText(e.request_id ?? "")}
                        >
                          복사
                        </button>
                      </span>
                    )}
                    {e.user_id && <span>사용자 {e.user_id.slice(0, 8)}</span>}
                    {e.workspace_id && <span>워크스페이스 {e.workspace_id.slice(0, 8)}</span>}
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
        {(errors.data?.length ?? 0) > 0 && (
          <ListPager c={c} className="border-t border-slate-100 px-4 py-2 sm:px-5" />
        )}
      </CardBody>
    </Card>
  );
}

export function StatusSection() {
  const st = useSystemStatus();
  const d = st.data;
  return (
    <div className="space-y-5">
      {st.isLoading && <Loading />}
      <ErrorBox error={st.error} />
      {d && (
        <>
          <Card className="flex flex-wrap items-center gap-3 p-4 sm:p-5">
            <StatusIcon s={d.overall} />
            <div className="min-w-0 flex-1">
              <p className="font-semibold text-slate-900">
                {d.overall === "ok"
                  ? "모두 정상이에요"
                  : d.overall === "warn"
                    ? "살펴볼 것이 있어요"
                    : d.overall === "error"
                      ? "문제가 있어요"
                      : "일부를 확인할 수 없어요"}
              </p>
              <p className="text-xs text-slate-500">
                버전 {d.version} · {formatDate(d.checked_at)} 확인 · 30초마다 새로 확인해요
              </p>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void st.refetch()}
              disabled={st.isFetching}
            >
              <RefreshCw className={cn("h-3.5 w-3.5", st.isFetching && "animate-spin")} /> 다시 확인
            </Button>
          </Card>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {d.items.map((it) => (
              <Card key={it.label} className="flex items-start gap-3 p-4">
                <StatusIcon s={it.status} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="font-medium text-slate-900">{it.label}</p>
                    <Badge tone={LOOK[it.status].tone}>{LOOK[it.status].label}</Badge>
                  </div>
                  <p className="mt-0.5 break-words text-xs text-slate-500">{it.detail}</p>
                </div>
              </Card>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            <StatTile
              icon={<Users className="h-3.5 w-3.5" />}
              label="사용자"
              value={d.counts.users}
            />
            <StatTile
              icon={<Workflow className="h-3.5 w-3.5" />}
              label="워크스페이스"
              value={d.counts.workspaces}
            />
            <StatTile
              icon={<Activity className="h-3.5 w-3.5" />}
              label="실행(24시간)"
              value={d.counts.runs_24h.toLocaleString()}
            />
            <StatTile
              icon={<XCircle className="h-3.5 w-3.5" />}
              label="실패한 실행(24시간)"
              value={d.counts.failed_runs_24h.toLocaleString()}
            />
            <StatTile
              icon={<AlertTriangle className="h-3.5 w-3.5" />}
              label="서버 오류(24시간)"
              value={d.counts.server_errors_24h.toLocaleString()}
            />
          </div>
        </>
      )}
      <ErrorsCard />
    </div>
  );
}
