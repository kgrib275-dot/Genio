// 관리 > 전체 회사(서비스 관리자 전용): 회사별 사람·앱·이번 달 사용량과 마지막 활동. 앱·대화 내용은 보여 주지 않는다.
import { StatTile } from "@/components/charts";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { useNavigate } from "react-router-dom";
import { useCompanies, type CompanyRow } from "@/lib/api/ops";
import { useSession } from "@/store/session";
import { useSupport } from "@/store/support";
import { formatCost, formatDate, timeAgo } from "@/lib/cn";
import { useListControls } from "@/lib/useListControls";

export function CompaniesSection() {
  const q = useCompanies();
  const navigate = useNavigate();
  const { workspaceId, role, setWorkspace } = useSession();
  const enter = useSupport((s) => s.enter);
  const help = (c: CompanyRow) => {
    if (c.support_access === "off") return;
    enter({
      id: c.id,
      name: c.name,
      level: c.support_access === "edit" ? "edit" : "read",
      back: { id: workspaceId, role },
    });
    setWorkspace(c.id, "admin");
    navigate("/");
  };
  const lc = useListControls<CompanyRow>(q.data?.items, {
    key: "companies",
    search: (c) => `${c.name} ${c.slug} ${c.owners.join(" ")}`,
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data;
  if (!d) return null;
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-500">
        이 서비스에 있는 모든 회사(워크스페이스)의 현황이에요. 사람 수·앱 수·이번 달 사용량만 보여
        주고, 앱과 대화 내용은 여기서 안 보이고, &apos;도와주기&apos;로 들어가면 회사가 허용한
        만큼(보기만 또는 수정까지) 볼 수 있어요. 열람과 수정은 그 회사의 활동 기록에 남아요.
      </p>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatTile label="회사" value={d.totals.workspaces.toLocaleString()} />
        <StatTile label="사람" value={d.totals.members.toLocaleString()} />
        <StatTile label="앱" value={d.totals.apps.toLocaleString()} />
        <StatTile label="이번 달 실행" value={d.totals.month_runs.toLocaleString()} />
        <StatTile label="이번 달 비용" value={formatCost(d.totals.month_cost)} />
      </div>
      <ListToolbar c={lc} placeholder="회사 이름·소유자로 찾기" />
      <NoMatch c={lc} />
      <Card className="overflow-hidden">
        <CardBody className="p-0">
          <ul className="divide-y divide-slate-100">
            {lc.pageItems.map((c) => {
              const over =
                c.monthly_budget_usd != null &&
                c.monthly_budget_usd > 0 &&
                c.month_cost >= c.monthly_budget_usd * 0.8;
              return (
                <li
                  key={c.id}
                  className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-sm"
                >
                  <div className="min-w-0 flex-1 basis-48">
                    <p className="flex items-center gap-1.5 font-medium text-slate-900">
                      {c.name}
                      {c.is_instance && <Badge tone="indigo">관리 회사</Badge>}
                    </p>
                    <p className="text-xs text-slate-500">소유자 {c.owners.join(", ") || "없음"}</p>
                  </div>
                  <span className="text-slate-600">사람 {c.members}</span>
                  <span className="text-slate-600">
                    앱 {c.apps}
                    <span className="text-xs text-slate-400"> (공개 {c.published_apps})</span>
                  </span>
                  <span className="text-slate-600">이번 달 {c.month_runs.toLocaleString()}번</span>
                  <span className={over ? "font-medium text-amber-700" : "text-slate-600"}>
                    {formatCost(c.month_cost)}
                    {c.monthly_budget_usd ? ` / ${formatCost(c.monthly_budget_usd)}` : ""}
                  </span>
                  {!c.is_instance && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={c.support_access === "off"}
                      title={
                        c.support_access === "off"
                          ? "이 회사가 지원 접속을 꺼 두었어요."
                          : c.support_access === "edit"
                            ? "들어가서 보고 고칠 수 있어요(멤버·키·한도 제외)."
                            : "들어가서 볼 수만 있어요."
                      }
                      onClick={() => help(c)}
                    >
                      {c.support_access === "off" ? "접속 꺼짐" : "도와주기"}
                    </Button>
                  )}
                  <span
                    className="w-24 text-right text-xs text-slate-400"
                    title={formatDate(c.last_active_at)}
                  >
                    {c.last_active_at ? timeAgo(c.last_active_at) : "활동 없음"}
                  </span>
                </li>
              );
            })}
          </ul>
        </CardBody>
      </Card>
      <ListPager c={lc} />
    </div>
  );
}
