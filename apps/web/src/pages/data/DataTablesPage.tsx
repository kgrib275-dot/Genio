// 데이터 표(n8n Data Tables·Make Data store): 흐름이 값을 적어 두고 다시 꺼내 쓰는 작은 표
import { ArrowLeft, Lock, Pencil, Plus, Table2, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { ProjectDot } from "@/components/projects/ProjectDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, Empty, PageHeader } from "@/components/ui/card";
import { toast } from "@/components/ui/toast-store";
import { HelpButton } from "@/help/HelpButton";
import type { DataTable } from "@/lib/api/types";
import { useProjects } from "@/lib/api/v3";
import { useDataTables, useDeleteDataTable } from "@/lib/api/v4";
import { cn, timeAgo } from "@/lib/cn";
import { optionsFrom, useListControls } from "@/lib/useListControls";
import { RowsGrid } from "@/pages/data/RowsGrid";
import { TableDialog } from "@/pages/data/TableDialog";
import { COLUMN_TYPES } from "@/pages/data/values";
import { canEdit, canViewRuns, useSession } from "@/store/session";

const TYPE_LABEL = Object.fromEntries(COLUMN_TYPES.map((t) => [t.value, t.label]));

export default function DataTablesPage() {
  const { tableId = "" } = useParams();
  const navigate = useNavigate();
  const { workspaceId: ws, role } = useSession();
  const tables = useDataTables(ws);
  const projects = useProjects(ws);
  const del = useDeleteDataTable(ws);
  const [dialog, setDialog] = useState<{ editing: DataTable | null } | null>(null);
  const editable = canEdit(role);
  const projectOf = (id: string | null) => projects.data?.find((p) => p.id === id);

  const c = useListControls(tables.data, {
    key: "data-tables",
    search: (t) => `${t.name} ${t.description} ${t.columns.map((x) => x.label).join(" ")}`,
    filters: [
      {
        id: "project",
        label: "프로젝트",
        options: [
          { value: "none", label: "프로젝트 없음" },
          ...optionsFrom(
            tables.data,
            (t) => t.project_id,
            (id) => projectOf(id)?.name ?? "프로젝트",
          ),
        ],
        match: (t, v) => (v === "none" ? !t.project_id : t.project_id === v),
      },
    ],
  });

  const selected = tables.data?.find((t) => t.id === tableId);
  const selProject = selected ? projectOf(selected.project_id) : undefined;

  return (
    <PageContainer>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <Table2 className="h-6 w-6 text-indigo-500" /> 데이터 표
          </span>
        }
        description="흐름이 값을 적어 두고 다시 꺼내 쓰는 작은 표예요. 엑셀 시트처럼 줄과 칸이 있어요."
        help={<HelpButton page="datatables" />}
        action={
          editable && (
            <Button onClick={() => setDialog({ editing: null })}>
              <Plus className="h-4 w-4" /> 새 표
            </Button>
          )
        }
      />

      {tables.isLoading && <Loading />}
      <ErrorBox error={tables.error} />

      {tables.data && tables.data.length === 0 && (
        <Empty icon={<Table2 className="h-10 w-10" />}>
          <p className="font-medium text-slate-700">아직 데이터 표가 없어요</p>
          <p className="max-w-md">
            문의 기록, 처리한 주문 번호, 고객 목록처럼 흐름이 기억해야 할 값을 담아 두세요. 흐름에서{" "}
            <b>데이터 표</b> 단계로 넣고 찾을 수 있어요.
          </p>
          {editable && (
            <Button className="mt-2" onClick={() => setDialog({ editing: null })}>
              <Plus className="h-4 w-4" /> 첫 표 만들기
            </Button>
          )}
        </Empty>
      )}

      {tables.data && tables.data.length > 0 && (
        <div className="grid gap-5 lg:grid-cols-[17rem_minmax(0,1fr)]">
          {/* 표 목록(좁은 화면에서는 표를 고르면 숨김) */}
          <div className={cn("min-w-0 space-y-3", tableId && "hidden lg:block")}>
            <ListToolbar c={c} placeholder="표 이름 검색" />
            <Card className="overflow-hidden">
              <ul className="divide-y divide-slate-100">
                {c.pageItems.map((t) => {
                  const p = projectOf(t.project_id);
                  return (
                    <li key={t.id}>
                      <Link
                        to={`/data/${t.id}`}
                        className={cn(
                          "block px-4 py-3 hover:bg-slate-50",
                          t.id === tableId && "bg-indigo-50 hover:bg-indigo-50",
                        )}
                      >
                        <p className="flex items-center gap-1.5 truncate text-sm font-semibold text-slate-900">
                          {p && <ProjectDot color={p.color} />}
                          {t.name}
                          {p?.visibility === "private" && (
                            <Lock className="h-3 w-3 text-slate-400" aria-label="비공개" />
                          )}
                        </p>
                        <p className="mt-0.5 text-xs text-slate-500">
                          {t.row_count.toLocaleString()}줄 · 칸 {t.columns.length}개 ·{" "}
                          {timeAgo(t.updated_at)}
                        </p>
                      </Link>
                    </li>
                  );
                })}
              </ul>
              <NoMatch c={c} />
            </Card>
            {c.total > 10 && <ListPager c={c} />}
          </div>

          {/* 고른 표 */}
          <div className={cn("min-w-0", !tableId && "hidden lg:block")}>
            {!tableId && (
              <Empty icon={<Table2 className="h-8 w-8" />}>왼쪽에서 표를 고르세요.</Empty>
            )}
            {tableId && !selected && tables.data && (
              <div
                role="alert"
                className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm"
              >
                <p className="font-medium text-red-800">표를 찾을 수 없어요.</p>
                <p className="text-red-700">
                  지워졌거나 볼 수 없는 프로젝트의 표예요. 목록에서 다른 표를 고르세요.
                </p>
              </div>
            )}
            {selected && (
              <div className="space-y-4">
                <div className="flex flex-wrap items-start gap-3">
                  <button
                    type="button"
                    onClick={() => navigate("/data")}
                    aria-label="표 목록으로"
                    className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 lg:hidden"
                  >
                    <ArrowLeft className="h-5 w-5" />
                  </button>
                  <div className="min-w-0 flex-1">
                    <h2 className="flex items-center gap-2 text-lg font-bold text-slate-900">
                      {selected.name}
                      {selProject && (
                        <Badge tone="indigo">
                          <ProjectDot color={selProject.color} /> {selProject.name}
                        </Badge>
                      )}
                    </h2>
                    {selected.description && (
                      <p className="mt-0.5 text-sm text-slate-500">{selected.description}</p>
                    )}
                    <div className="mt-2 flex flex-wrap gap-1">
                      {selected.columns.map((col) => (
                        <span
                          key={col.key}
                          className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600"
                          title={`흐름에서는 ${col.key}로 써요`}
                        >
                          {col.label || col.key}{" "}
                          <span className="text-slate-400">
                            · {TYPE_LABEL[col.type] ?? col.type}
                          </span>
                        </span>
                      ))}
                    </div>
                  </div>
                  {editable && (
                    <div className="flex gap-1">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setDialog({ editing: selected })}
                      >
                        <Pencil className="h-3.5 w-3.5" /> 표 고치기
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-red-600"
                        aria-label="표 지우기"
                        disabled={del.isPending}
                        onClick={() => {
                          if (
                            window.confirm(
                              `'${selected.name}' 표와 줄 ${selected.row_count}개를 모두 지울까요? 이 표를 쓰는 흐름은 실패하게 돼요.`,
                            )
                          )
                            del.mutate(selected.id, {
                              onSuccess: () => {
                                toast.success("표를 지웠어요.");
                                navigate("/data");
                              },
                              onError: (err) => toast.error(err),
                            });
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  )}
                </div>
                <RowsGrid
                  ws={ws}
                  table={selected}
                  canEditRows={canViewRuns(role)}
                  canEditTable={editable}
                />
              </div>
            )}
          </div>
        </div>
      )}

      {dialog && (
        <TableDialog
          ws={ws}
          editing={dialog.editing}
          onClose={() => setDialog(null)}
          onSaved={(t) => {
            setDialog(null);
            toast.success(dialog.editing ? "표를 고쳤어요." : "표를 만들었어요.");
            navigate(`/data/${t.id}`);
          }}
        />
      )}
    </PageContainer>
  );
}
