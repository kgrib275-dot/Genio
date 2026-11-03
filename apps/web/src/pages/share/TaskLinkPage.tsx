// 이메일·슬랙으로 받은 링크(/t/:token)에서 로그인 없이 승인·답·완료를 처리하는 화면.
import { CheckCircle2, ClipboardList, Clock } from "lucide-react";
import { useParams } from "react-router-dom";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Badge } from "@/components/ui/badge";
import { Markdown } from "@/components/chat/Markdown";
import { ko } from "@/i18n/ko";
import { formatDate } from "@/lib/cn";
import {
  TASK_KIND_LABEL,
  TASK_STATUS_LABEL,
  useCompletePublicTask,
  usePublicTask,
} from "@/lib/api/v5a";
import { TaskForm } from "@/pages/tasks/TaskForm";

export default function TaskLinkPage() {
  const { token = "" } = useParams();
  const task = usePublicTask(token);
  const complete = useCompletePublicTask(token);

  return (
    <div className="flex min-h-[100dvh] items-start justify-center bg-slate-50 px-4 py-10 sm:items-center">
      <div className="w-full max-w-lg">
        <p className="mb-4 flex items-center justify-center gap-2 text-sm font-semibold text-slate-500">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-gradient-to-br from-indigo-500 to-violet-600 text-xs font-bold text-white">
            G
          </span>
          {ko.appName}
        </p>
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          {task.isLoading && <Loading />}
          <ErrorBox error={task.error} />
          {task.data && (
            <div className="space-y-4">
              <div>
                <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                  <ClipboardList className="h-3.5 w-3.5" />
                  <span>{task.data.app_name}</span>
                  <Badge tone="blue">{TASK_KIND_LABEL[task.data.kind]}</Badge>
                  <Badge tone={task.data.status === "open" ? "amber" : "gray"}>
                    {TASK_STATUS_LABEL[task.data.status]}
                  </Badge>
                </div>
                <h1 className="mt-2 text-lg font-bold text-slate-900">{task.data.title}</h1>
                {task.data.detail && (
                  <div className="mt-2 text-sm text-slate-600">
                    <Markdown text={task.data.detail} />
                  </div>
                )}
                {task.data.due_at && task.data.status === "open" && (
                  <p className="mt-2 flex items-center gap-1 text-xs text-amber-700">
                    <Clock className="h-3.5 w-3.5" /> 기한 {formatDate(task.data.due_at)}
                  </p>
                )}
              </div>
              {task.data.status === "open" ? (
                <TaskForm
                  task={task.data}
                  pending={complete.isPending}
                  error={complete.error}
                  onSubmit={(body) => complete.mutate(body)}
                />
              ) : (
                <div className="flex items-start gap-2 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                  <div>
                    <p className="font-semibold">
                      {task.data.status === "done" ? "처리했어요." : "취소된 요청이에요."}
                    </p>
                    <p className="text-emerald-700">
                      {task.data.status === "done"
                        ? "흐름이 다음 단계로 이어졌어요. 이 창은 닫아도 돼요."
                        : "요청한 사람에게 다시 확인해 주세요."}
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
        <p className="mt-3 text-center text-[11px] text-slate-400">
          이 링크는 받은 사람만 쓰도록 보내졌어요. 다른 사람에게 전달하지 마세요.
        </p>
      </div>
    </div>
  );
}
