// 작업함: 흐름이 나에게(또는 내 역할에) 맡긴 승인·질문·할 일을 모아 보고 처리한다.
import { ClipboardList, Clock, ExternalLink, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { Markdown } from "@/components/chat/Markdown";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Tabs } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toast-store";
import { ko } from "@/i18n/ko";
import { formatDate, timeAgo } from "@/lib/cn";
import { optionsFrom, useListControls } from "@/lib/useListControls";
import {
  TASK_KIND_LABEL,
  TASK_STATUS_LABEL,
  useCancelTask,
  useCompleteTask,
  useTasks,
  type HumanTask,
  type TaskStatus,
} from "@/lib/api/v5a";
import { canEdit, canViewRuns, useSession } from "@/store/session";
import { TaskForm } from "@/pages/tasks/TaskForm";
import { EmptyState } from "@/components/EmptyState";

type View = "mine" | "all" | "done";

const VIEWS: { value: View; label: string }[] = [
  { value: "mine", label: "내가 할 일" },
  { value: "all", label: "모든 열린 일" },
  { value: "done", label: "끝난 일" },
];

const KIND_TONE = { approval: "indigo", question: "blue", assignment: "amber" } as const;

function overdue(t: HumanTask) {
  return t.status === "open" && t.due_at && new Date(t.due_at).getTime() < Date.now();
}

export default function TasksPage() {
  const { workspaceId: ws, role } = useSession();
  const [view, setView] = useState<View>("mine");
  const status: TaskStatus | "all" = view === "done" ? "all" : "open";
  const list = useTasks(ws, { status, mine: view === "mine" });
  const items = (list.data ?? []).filter((t) => (view === "done" ? t.status !== "open" : true));
  const [openId, setOpenId] = useState<string | null>(null);
  const complete = useCompleteTask(ws);
  const cancel = useCancelTask(ws);
  const current = items.find((t) => t.id === openId) ?? null;

  const lc = useListControls(items, {
    key: `tasks-${view}`,
    search: (t) => `${t.title} ${t.detail} ${t.app_name}`,
    filters: [
      {
        id: "kind",
        label: "종류",
        options: (["approval", "question", "assignment"] as const).map((k) => ({
          value: k,
          label: TASK_KIND_LABEL[k],
        })),
        match: (t, v) => t.kind === v,
      },
      {
        id: "app",
        label: "앱",
        options: optionsFrom(items, (t) => t.app_name),
        match: (t, v) => t.app_name === v,
      },
      ...(view === "done"
        ? [
            {
              id: "status",
              label: "상태",
              options: [
                { value: "done", label: TASK_STATUS_LABEL.done },
                { value: "cancelled", label: TASK_STATUS_LABEL.cancelled },
              ],
              match: (t: HumanTask, v: string) => t.status === v,
            },
          ]
        : []),
    ],
  });

  return (
    <PageContainer>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <ClipboardList className="h-6 w-6 text-indigo-500" /> 작업함
          </span>
        }
        description="흐름이 사람에게 맡긴 승인·질문·할 일이 모여요. 처리하면 흐름이 바로 이어져요."
      />
      <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <Tabs value={view} onChange={setView} items={VIEWS} />
      </div>
      {list.isLoading && <Loading />}
      <ErrorBox error={list.error} />
      {!list.isLoading && items.length === 0 ? (
        <EmptyState
          icon={<ClipboardList className="h-5 w-5" />}
          title={view === "done" ? "아직 끝난 일이 없어요" : "지금 처리할 일이 없어요"}
          description="흐름에 '승인'·'사람에게 묻기'·'담당자 배정' 단계를 넣으면, 사람이 처리할 일이 여기로 와요."
          secondary={{ label: "승인 흐름 샘플 보기", to: "/learn" }}
        />
      ) : (
        <div className="space-y-3">
          <ListToolbar c={lc} placeholder="제목·내용·앱 검색" />
          <Card className="overflow-hidden">
            <ul className="divide-y divide-slate-100">
              {lc.pageItems.map((t) => (
                <li key={t.id}>
                  <button
                    type="button"
                    onClick={() => setOpenId(t.id)}
                    className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-left hover:bg-slate-50"
                  >
                    <Badge tone={KIND_TONE[t.kind]}>{TASK_KIND_LABEL[t.kind]}</Badge>
                    <span className="min-w-0 flex-1 basis-48 truncate text-sm font-medium text-slate-900">
                      {t.title}
                    </span>
                    <span className="text-xs text-slate-500">{t.app_name}</span>
                    {t.assignee_role && (
                      <span className="text-xs text-slate-400">
                        {ko.roles[t.assignee_role as keyof typeof ko.roles] ?? t.assignee_role}
                      </span>
                    )}
                    {t.status === "open" ? (
                      <span
                        className={
                          overdue(t)
                            ? "inline-flex items-center gap-1 text-xs font-medium text-red-600"
                            : "inline-flex items-center gap-1 text-xs text-slate-400"
                        }
                      >
                        <Clock className="h-3 w-3" />
                        {t.due_at ? `기한 ${formatDate(t.due_at)}` : timeAgo(t.created_at)}
                      </span>
                    ) : (
                      <Badge tone={t.status === "done" ? "green" : "gray"}>
                        {TASK_STATUS_LABEL[t.status]}
                      </Badge>
                    )}
                  </button>
                </li>
              ))}
            </ul>
            <NoMatch c={lc} />
          </Card>
          <ListPager c={lc} />
        </div>
      )}

      <Dialog
        open={current !== null}
        onClose={() => setOpenId(null)}
        title={current ? `${TASK_KIND_LABEL[current.kind]} · ${current.app_name}` : ""}
      >
        {current && (
          <div className="space-y-4">
            <div>
              <h2 className="text-base font-bold text-slate-900">{current.title}</h2>
              {current.detail && (
                <div className="mt-1.5 text-sm text-slate-600">
                  <Markdown text={current.detail} />
                </div>
              )}
              <p className="mt-2 text-xs text-slate-400">
                요청 {timeAgo(current.created_at)}
                {current.due_at && ` · 기한 ${formatDate(current.due_at)}`}
                {current.run_id && canViewRuns(role) && (
                  <>
                    {" · "}
                    <Link
                      to={`/runs/${current.run_id}`}
                      className="inline-flex items-center gap-0.5 text-indigo-600 hover:underline"
                    >
                      실행 보기 <ExternalLink className="h-3 w-3" />
                    </Link>
                  </>
                )}
              </p>
            </div>
            {current.status === "open" && current.can_act ? (
              <TaskForm
                task={current}
                pending={complete.isPending}
                error={complete.error}
                onSubmit={(body) =>
                  complete.mutate(
                    { id: current.id, ...body },
                    {
                      onSuccess: () => {
                        toast.success("처리했어요. 흐름이 다음 단계로 이어져요.");
                        setOpenId(null);
                      },
                    },
                  )
                }
              />
            ) : current.status === "open" ? (
              <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">
                이 일은 다른 담당자가 처리해요. 볼 수만 있어요.
              </p>
            ) : (
              <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
                <p className="font-medium">{TASK_STATUS_LABEL[current.status]}</p>
                {Object.entries(current.response ?? {})
                  .filter(([, v]) => v !== "" && v !== null && v !== undefined)
                  .map(([k, v]) => (
                    <p key={k} className="text-xs text-slate-500">
                      {k === "approved" ? (v ? "승인" : "반려") : `${k}: ${String(v)}`}
                    </p>
                  ))}
              </div>
            )}
            {current.status === "open" && canEdit(role) && (
              <button
                type="button"
                className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-red-600"
                disabled={cancel.isPending}
                onClick={() => {
                  if (window.confirm("이 요청을 취소할까요? 기다리던 흐름은 멈춰요."))
                    cancel.mutate(current.id, {
                      onSuccess: () => {
                        toast.success("요청을 취소했어요.");
                        setOpenId(null);
                      },
                      onError: (err) => toast.error(err),
                    });
                }}
              >
                <X className="h-3 w-3" /> 요청 취소
              </button>
            )}
            {current.status !== "open" && (
              <Button variant="outline" className="w-full" onClick={() => setOpenId(null)}>
                닫기
              </Button>
            )}
          </div>
        )}
      </Dialog>
    </PageContainer>
  );
}
