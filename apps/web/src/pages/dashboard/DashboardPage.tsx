import { ArrowRight, LayoutTemplate, Plus, Sparkles, Wand2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { AppIcon } from "@/components/AppIcon";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, Empty } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { ko } from "@/i18n/ko";
import { useApps, useCreateApp } from "@/lib/api/apps";
import { useTemplates } from "@/lib/api/resources";
import type { AppType } from "@/lib/api/types";
import { useWorkspaceRuns } from "@/lib/api/workspace";
import { timeAgo } from "@/lib/cn";
import { canEdit, canViewRuns, useSession } from "@/store/session";
import { setPendingPrompt } from "@/store/pendingPrompt";

const SUGGESTIONS = [
  "고객 문의 메일을 분류해서 담당자 슬랙으로 보내 줘",
  "사내 규정 문서로 질문에 답하는 챗봇을 만들어 줘",
  "주간 보고 초안을 만들어서 승인 후 메일로 보내 줘",
  "회의 메모를 받아 할 일 목록으로 정리해 줘",
];

function appNameFrom(prompt: string): string {
  const clean = prompt
    .replace(/\s+/g, " ")
    .trim()
    .replace(/(해\s?줘|만들어\s?줘|줘)[.!?]*$/, "");
  return clean.length > 24 ? `${clean.slice(0, 24)}…` : clean || "새 앱";
}

/** 맨 위: 말로 앱 만들기 */
function PromptHero() {
  const ws = useSession((s) => s.workspaceId);
  const create = useCreateApp(ws);
  const navigate = useNavigate();
  const [text, setText] = useState("");

  const start = (prompt: string) => {
    const p = prompt.trim();
    if (!p || create.isPending) return;
    create.mutate(
      { name: appNameFrom(p), type: "chat", description: p, icon: "" },
      {
        onSuccess: (app) => {
          setPendingPrompt(app.id, p);
          navigate(`/apps/${app.id}/builder`);
        },
      },
    );
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    start(text);
  };

  return (
    <section className="relative overflow-hidden rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-violet-50 px-8 py-8">
      <div className="flex items-center gap-2 text-sm font-semibold text-indigo-600">
        <Sparkles className="h-4 w-4" /> 말로 앱 만들기
      </div>
      <h2 className="mt-2 text-[26px] font-bold tracking-tight text-slate-900">
        무엇을 자동으로 처리하고 싶으세요?
      </h2>
      <p className="mt-1 text-sm text-slate-500">
        평소 말하듯 적으면 빌더가 흐름을 만들고, 필요한 것은 되물어 봐요.
      </p>
      <form onSubmit={submit} className="mt-5">
        <div className="flex items-end gap-2 rounded-xl border border-slate-200 bg-white p-2 shadow-lift focus-within:border-indigo-400 focus-within:ring-4 focus-within:ring-indigo-500/10">
          <textarea
            aria-label="만들고 싶은 앱 설명"
            rows={2}
            className="min-h-[52px] flex-1 resize-none border-0 bg-transparent px-2 py-1.5 text-[15px] placeholder:text-slate-400 focus:outline-none"
            placeholder="예: 고객 문의 메일을 분류해서 담당자 슬랙으로 보내 줘"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                start(text);
              }
            }}
          />
          <Button type="submit" className="h-11 px-5" disabled={!text.trim() || create.isPending}>
            <Wand2 className="h-4 w-4" />
            {create.isPending ? "만드는 중…" : "만들기"}
          </Button>
        </div>
      </form>
      <div className="mt-3 flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => start(s)}
            disabled={create.isPending}
            className="rounded-full border border-slate-200 bg-white/80 px-3 py-1.5 text-[13px] text-slate-600 transition-colors hover:border-indigo-300 hover:bg-white hover:text-indigo-700"
          >
            {s}
          </button>
        ))}
      </div>
      <ErrorBox error={create.error} />
    </section>
  );
}

function TemplateRow() {
  const ws = useSession((s) => s.workspaceId);
  const templates = useTemplates(ws);
  const create = useCreateApp(ws);
  const navigate = useNavigate();
  const list = templates.data ?? [];
  if (list.length === 0) return null;
  return (
    <section className="mt-8">
      <div className="mb-3 flex items-center gap-2">
        <LayoutTemplate className="h-4 w-4 text-slate-400" />
        <h3 className="text-sm font-semibold text-slate-700">템플릿으로 바로 시작</h3>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {list.map((t) => (
          <button
            key={t.key}
            type="button"
            disabled={create.isPending}
            onClick={() =>
              create.mutate(
                {
                  name: t.name,
                  type: "chat",
                  description: t.summary,
                  icon: "",
                  template_key: t.key,
                },
                { onSuccess: (app) => navigate(`/apps/${app.id}/builder`) },
              )
            }
            className="group flex flex-col items-start gap-2 rounded-xl border border-slate-200 bg-white p-4 text-left shadow-card transition-all hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-lift"
          >
            <AppIcon name={t.name} size="sm" />
            <p className="text-sm font-semibold text-slate-800">{t.name}</p>
            <p className="line-clamp-2 text-xs leading-relaxed text-slate-500">{t.summary}</p>
          </button>
        ))}
      </div>
    </section>
  );
}

function BlankAppDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ws = useSession((s) => s.workspaceId);
  const create = useCreateApp(ws);
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: "", type: "chat" as AppType, description: "" });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { ...form, icon: "" },
      {
        onSuccess: (app) => {
          onClose();
          navigate(`/apps/${app.id}/builder`);
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="빈 앱 만들기"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {ko.common.cancel}
          </Button>
          <Button type="submit" form="create-app" disabled={create.isPending || !form.name}>
            {ko.common.create}
          </Button>
        </>
      }
    >
      <form id="create-app" onSubmit={submit} className="space-y-4">
        <Field label="앱 이름" htmlFor="app-name">
          <Input
            id="app-name"
            required
            placeholder="예: 고객 문의 분류기"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </Field>
        <Field label="종류" htmlFor="app-type">
          <Select
            id="app-type"
            value={form.type}
            onChange={(e) => setForm({ ...form, type: e.target.value as AppType })}
          >
            {(Object.keys(ko.appTypes) as AppType[]).map((t) => (
              <option key={t} value={t}>
                {ko.appTypes[t]}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="설명(선택)" htmlFor="app-desc">
          <Textarea
            id="app-desc"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </Field>
        <ErrorBox error={create.error} />
      </form>
    </Dialog>
  );
}

export default function DashboardPage() {
  const { workspaceId: ws, role } = useSession();
  const apps = useApps(ws);
  const runs = useWorkspaceRuns(ws, {}, canViewRuns(role));
  const [open, setOpen] = useState(false);
  const editable = canEdit(role);
  const appList = apps.data ?? [];

  return (
    <PageContainer>
      {editable && <PromptHero />}
      {editable && <TemplateRow />}

      <section className="mt-10">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-lg font-bold tracking-tight">
            {editable ? "내 앱" : "사용할 수 있는 앱"}
            {appList.length > 0 && (
              <span className="ml-2 text-sm font-medium text-slate-400">{appList.length}</span>
            )}
          </h3>
          {editable && (
            <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
              <Plus className="h-4 w-4" /> 빈 앱
            </Button>
          )}
        </div>
        {apps.isLoading && <Loading />}
        <ErrorBox error={apps.error} />
        {apps.data && appList.length === 0 && (
          <Empty>
            {editable
              ? "아직 앱이 없어요. 위에 만들고 싶은 것을 적어 보세요."
              : "아직 사용할 수 있는 앱이 없어요. 관리자가 앱을 배포하면 여기에 보여요."}
          </Empty>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {appList.map((app) => {
            const body = (
              <Card className="group h-full p-4 transition-all hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-lift">
                <div className="flex items-start gap-3">
                  <AppIcon name={app.name} icon={app.icon} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold text-slate-900">{app.name}</p>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {ko.appTypes[app.type]} ·{" "}
                      {app.latest_version ? `버전 ${app.latest_version}` : "저장 전"} ·{" "}
                      {timeAgo(app.updated_at)}
                    </p>
                  </div>
                  <StatusBadge status={app.status} />
                </div>
                {app.description && (
                  <p className="mt-3 line-clamp-2 text-[13px] leading-relaxed text-slate-500">
                    {app.description}
                  </p>
                )}
                {editable && (
                  <p className="mt-3 flex items-center gap-1 text-xs font-medium text-indigo-600 opacity-0 transition-opacity group-hover:opacity-100">
                    열어서 고치기 <ArrowRight className="h-3 w-3" />
                  </p>
                )}
              </Card>
            );
            return canViewRuns(role) ? (
              <Link key={app.id} to={editable ? `/apps/${app.id}/builder` : `/apps/${app.id}/runs`}>
                {body}
              </Link>
            ) : (
              <div key={app.id}>{body}</div>
            );
          })}
        </div>
      </section>

      {canViewRuns(role) && (runs.data ?? []).length > 0 && (
        <section className="mt-10">
          <h3 className="mb-3 text-lg font-bold tracking-tight">최근 실행</h3>
          <Card className="overflow-hidden">
            <ul className="divide-y divide-slate-100">
              {(runs.data ?? []).slice(0, 8).map((r) => (
                <li key={r.id}>
                  <Link
                    to={`/runs/${r.id}`}
                    className="flex items-center gap-3 px-4 py-3 text-sm hover:bg-slate-50"
                  >
                    <AppIcon name={r.app_name ?? "앱"} size="sm" />
                    <span className="min-w-0 flex-1 truncate font-medium text-slate-800">
                      {r.app_name ?? "앱"}
                    </span>
                    <span className="hidden text-xs text-slate-400 sm:inline">
                      {{ test: "테스트", chat: "챗", api: "API", schedule: "예약" }[r.trigger] ??
                        r.trigger}
                    </span>
                    <span className="w-16 text-right text-xs text-slate-400">
                      {timeAgo(r.created_at)}
                    </span>
                    <StatusBadge status={r.status} />
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </section>
      )}
      <BlankAppDialog open={open} onClose={() => setOpen(false)} />
    </PageContainer>
  );
}
