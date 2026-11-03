import {
  GraduationCap,
  ArrowRight,
  FolderInput,
  LayoutTemplate,
  Lock,
  MoreHorizontal,
  Plus,
  Settings2,
  Sparkles,
  Upload,
  Users,
  Wand2,
} from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { AppIcon, Avatar } from "@/components/AppIcon";
import { ProjectDialog, ProjectDot } from "@/components/projects/ProjectDialog";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, Empty } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { ko } from "@/i18n/ko";
import { useApps, useCreateApp, useUpdateApp } from "@/lib/api/apps";
import { useMe } from "@/lib/api/auth";
import { useTemplates } from "@/lib/api/resources";
import { ApiError, api } from "@/lib/api/client";
import type { App, AppExport, AppType, Project } from "@/lib/api/types";
import { useImportApp } from "@/lib/api/v2";
import { useProjects } from "@/lib/api/v3";
import { HelpButton } from "@/help/HelpButton";
import { toast } from "@/components/ui/toast-store";
import { useWorkspaceRuns } from "@/lib/api/workspace";
import { cn, timeAgo } from "@/lib/cn";
import { useListControls } from "@/lib/useListControls";
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
function PromptHero({ projectId }: { projectId?: string }) {
  const ws = useSession((s) => s.workspaceId);
  const create = useCreateApp(ws);
  const navigate = useNavigate();
  const [text, setText] = useState("");

  const start = (prompt: string) => {
    const p = prompt.trim();
    if (!p || create.isPending) return;
    create.mutate(
      { name: appNameFrom(p), type: "chat", description: p, icon: "", project_id: projectId },
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
    <section className="relative overflow-hidden rounded-2xl border border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-violet-50 px-5 py-6 sm:px-8 sm:py-8">
      <div className="flex items-center gap-2 text-sm font-semibold text-indigo-600">
        <Sparkles className="h-4 w-4" /> 말로 앱 만들기
      </div>
      <h2 className="mt-2 text-xl font-bold tracking-tight text-slate-900 sm:text-[26px]">
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

function TemplateRow({ projectId }: { projectId?: string }) {
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
                  project_id: projectId,
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

/** 내보낸 앱 파일(JSON)을 올려 새 앱으로 가져온다. */
function ImportAppButton({ projectId }: { projectId?: string }) {
  const ws = useSession((s) => s.workspaceId);
  const importApp = useImportApp(ws);
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={fileRef}
        type="file"
        accept=".json,application/json"
        className="hidden"
        aria-label="앱 파일"
        onChange={async (e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (!f) return;
          let data: AppExport;
          try {
            data = JSON.parse(await f.text()) as AppExport;
          } catch {
            toast.error(
              new ApiError(
                0,
                "앱 파일을 읽지 못했어요.",
                "내보내기로 받은 .json 파일인지 확인하세요.",
              ),
            );
            return;
          }
          importApp.mutate(data, {
            onSuccess: async (app) => {
              // 가져오기 API는 프로젝트를 받지 않아서, 고른 프로젝트로 바로 옮긴다
              if (projectId) {
                try {
                  await api.patch(`/apps/${app.id}`, { project_id: projectId });
                } catch (err) {
                  toast.error(err);
                }
              }
              toast.success("앱을 가져왔어요.");
              navigate(`/apps/${app.id}/builder`);
            },
            onError: (err) => toast.error(err),
          });
        }}
      />
      <Button
        size="sm"
        variant="outline"
        disabled={importApp.isPending}
        onClick={() => fileRef.current?.click()}
      >
        <Upload className="h-4 w-4" /> 앱 가져오기
      </Button>
    </>
  );
}

function BlankAppDialog({
  open,
  onClose,
  projectId,
}: {
  open: boolean;
  onClose: () => void;
  projectId?: string;
}) {
  const ws = useSession((s) => s.workspaceId);
  const create = useCreateApp(ws);
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: "", type: "chat" as AppType, description: "" });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { ...form, icon: "", project_id: projectId },
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

/** 위쪽 칩: 전체 / 프로젝트 없음 / 각 프로젝트 */
function ProjectChips({
  projects,
  value,
  onChange,
  onCreate,
}: {
  projects: Project[];
  value: string;
  onChange: (v: string) => void;
  onCreate?: () => void;
}) {
  const chip = (key: string, label: ReactNode, title?: string) => (
    <button
      key={key || "all"}
      type="button"
      title={title}
      aria-pressed={value === key}
      onClick={() => onChange(key)}
      className={cn(
        "inline-flex h-8 max-w-[14rem] shrink-0 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-colors",
        value === key
          ? "border-indigo-300 bg-indigo-50 font-semibold text-indigo-700"
          : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-900",
      )}
    >
      {label}
    </button>
  );
  return (
    <div
      role="toolbar"
      aria-label="프로젝트로 거르기"
      className="-mx-4 mb-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0"
    >
      {chip("", "전체")}
      {chip("none", "프로젝트 없음")}
      {projects.map((p) =>
        chip(
          p.id,
          <>
            <ProjectDot color={p.color} />
            <span className="truncate">{p.name}</span>
            {p.visibility === "private" && <Lock className="h-3 w-3 shrink-0 text-slate-400" />}
          </>,
          p.name,
        ),
      )}
      {onCreate && (
        <button
          type="button"
          onClick={onCreate}
          className="inline-flex h-8 shrink-0 items-center gap-1 rounded-full border border-dashed border-slate-300 px-3 text-[13px] text-slate-500 hover:border-indigo-300 hover:text-indigo-700"
        >
          <Plus className="h-3.5 w-3.5" /> 새 프로젝트
        </button>
      )}
    </div>
  );
}

function ProjectHeader({ project, onEdit }: { project: Project; onEdit: () => void }) {
  return (
    <Card className="mb-4 flex flex-wrap items-start gap-3 p-4">
      <ProjectDot color={project.color} className="mt-1.5 h-3 w-3" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="truncate text-base font-bold text-slate-900">{project.name}</h2>
          {project.visibility === "private" ? (
            <Badge tone="amber">
              <Lock className="h-3 w-3" /> 나와 고른 사람만
            </Badge>
          ) : (
            <Badge tone="blue">
              <Users className="h-3 w-3" /> 워크스페이스 전체
            </Badge>
          )}
        </div>
        {project.description && (
          <p className="mt-1 text-sm text-slate-500">{project.description}</p>
        )}
        <p className="mt-1 text-xs text-slate-400">
          앱 {project.app_count}개 · 지식 {project.knowledge_base_count}개 · 만든 사람{" "}
          {project.created_by_name}
        </p>
      </div>
      <div className="flex items-center gap-3">
        {project.visibility === "private" && project.members.length > 0 && (
          <div className="flex -space-x-2" aria-label="함께 보는 사람">
            {project.members.slice(0, 5).map((m) => (
              <span
                key={m.user_id}
                title={m.name}
                className="rounded-full ring-2 ring-[color:rgb(var(--surface))]"
              >
                <Avatar name={m.name} />
              </span>
            ))}
            {project.members.length > 5 && (
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-100 text-xs text-slate-600 ring-2 ring-[color:rgb(var(--surface))]">
                +{project.members.length - 5}
              </span>
            )}
          </div>
        )}
        {project.can_manage && (
          <Button size="sm" variant="outline" onClick={onEdit}>
            <Settings2 className="h-4 w-4" /> 프로젝트 설정
          </Button>
        )}
      </div>
    </Card>
  );
}

/** 앱을 다른 프로젝트로 옮기는 대화상자 */
export function MoveProjectDialog({
  app,
  projects,
  onClose,
}: {
  app: App | null;
  projects: Project[];
  onClose: () => void;
}) {
  const update = useUpdateApp(app?.id ?? "");
  const [target, setTarget] = useState("");
  useEffect(() => setTarget(app?.project_id ?? ""), [app]);
  if (!app) return null;
  const save = () =>
    update.mutate(
      { project_id: target },
      {
        onSuccess: () => {
          toast.success("앱을 옮겼어요.");
          onClose();
        },
        onError: (e) => toast.error(e),
      },
    );
  return (
    <Dialog
      open
      onClose={onClose}
      title="프로젝트 이동"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {ko.common.cancel}
          </Button>
          <Button onClick={save} disabled={update.isPending || target === (app.project_id ?? "")}>
            옮기기
          </Button>
        </>
      }
    >
      <Field label={`‘${app.name}’을(를) 옮길 곳`} htmlFor="move-project">
        <Select id="move-project" value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">프로젝트 없음</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </Select>
      </Field>
    </Dialog>
  );
}

function CardMenu({ onMove }: { onMove: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-label="앱 메뉴"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-8 z-20 w-40 rounded-lg border border-slate-200 bg-white py-1 shadow-lift"
        >
          <button
            type="button"
            role="menuitem"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setOpen(false);
              onMove();
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
          >
            <FolderInput className="h-4 w-4 text-slate-400" /> 프로젝트 이동
          </button>
        </div>
      )}
    </div>
  );
}

const LEARN_BANNER_KEY = "genio.learn.banner";

/** 처음 쓰는 사람에게 배우기를 안내한다. 닫으면 다시 안 보인다. */
function LearnBanner() {
  const [hidden, setHidden] = useState(() => {
    try {
      return window.localStorage.getItem(LEARN_BANNER_KEY) === "0";
    } catch {
      return false;
    }
  });
  if (hidden) return null;
  return (
    <div className="mb-6 flex flex-col gap-3 rounded-2xl border border-indigo-100 bg-gradient-to-r from-indigo-50 to-violet-50 p-4 sm:flex-row sm:items-center">
      <GraduationCap className="h-7 w-7 shrink-0 text-indigo-500" />
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-semibold text-slate-900">처음이세요? 샘플로 10분 만에 배워 보세요</p>
        <p className="text-slate-600">
          자주 묻는 질문 봇, 휴가 승인, 주문 접수 같은 샘플 11가지를 열어 따라 하는 강좌가 있어요.
        </p>
      </div>
      <div className="flex shrink-0 gap-2">
        <Link
          to="/learn"
          className="inline-flex h-9 items-center rounded-lg bg-indigo-600 px-3 text-sm font-semibold text-white hover:bg-indigo-700"
        >
          배우기 열기
        </Link>
        <button
          type="button"
          onClick={() => {
            setHidden(true);
            try {
              window.localStorage.setItem(LEARN_BANNER_KEY, "0");
            } catch {
              // 기억하지 못해도 괜찮다
            }
          }}
          className="h-9 rounded-lg px-3 text-sm text-slate-500 hover:bg-white/60"
        >
          닫기
        </button>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { workspaceId: ws, role } = useSession();
  const [params, setParams] = useSearchParams();
  const filter = params.get("project") ?? "";
  const me = useMe();
  const projects = useProjects(ws);
  const projectList = projects.data ?? [];
  const current = projectList.find((p) => p.id === filter) ?? null;
  // 지금 보고 있는 프로젝트. 여기서 새로 만드는 앱은 이 프로젝트에 들어간다
  const projectId = filter && filter !== "none" ? filter : undefined;
  const apps = useApps(ws, filter || undefined);
  const runs = useWorkspaceRuns(ws, {}, canViewRuns(role));
  const [open, setOpen] = useState(false);
  const [projectDialog, setProjectDialog] = useState<"new" | "edit" | null>(null);
  const [moving, setMoving] = useState<App | null>(null);
  const editable = canEdit(role);
  const appList = apps.data ?? [];
  const byId = new Map(projectList.map((p) => [p.id, p]));
  const c = useListControls(apps.data, {
    key: "dashboard-apps",
    defaultSize: 20,
    search: (a) => `${a.name} ${a.description}`,
    filters: [
      {
        id: "type",
        label: "종류",
        options: (Object.keys(ko.appTypes) as AppType[]).map((t) => ({
          value: t,
          label: ko.appTypes[t],
        })),
        match: (a, v) => a.type === v,
      },
      {
        id: "status",
        label: "상태",
        options: [
          { value: "published", label: "배포됨" },
          { value: "draft", label: "만드는 중" },
        ],
        match: (a, v) => a.status === v,
      },
    ],
  });
  const setFilter = (v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set("project", v);
    else next.delete("project");
    setParams(next, { replace: true });
  };

  return (
    <PageContainer>
      <LearnBanner />
      {editable && <PromptHero projectId={projectId} />}
      {editable && <TemplateRow projectId={projectId} />}

      <section className="mt-10">
        {(projectList.length > 0 || filter) && (
          <ProjectChips
            projects={projectList}
            value={filter}
            onChange={setFilter}
            onCreate={editable ? () => setProjectDialog("new") : undefined}
          />
        )}
        {current && <ProjectHeader project={current} onEdit={() => setProjectDialog("edit")} />}
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 className="flex items-center gap-1 text-lg font-bold tracking-tight">
            {current ? "프로젝트 앱" : editable ? "내 앱" : "사용할 수 있는 앱"}
            {appList.length > 0 && (
              <span className="ml-1 text-sm font-medium text-slate-400">{appList.length}</span>
            )}
            <HelpButton page="dashboard" />
          </h3>
          {editable && (
            <div className="flex gap-2">
              <ImportAppButton projectId={projectId} />
              <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
                <Plus className="h-4 w-4" /> 빈 앱
              </Button>
            </div>
          )}
        </div>
        {apps.isLoading && <Loading />}
        <ErrorBox error={apps.error} />
        {apps.data && appList.length === 0 && (
          <Empty>
            {filter
              ? editable
                ? "여기에는 아직 앱이 없어요. 위에 만들고 싶은 것을 적으면 이곳에 만들어져요."
                : "여기에는 아직 앱이 없어요."
              : editable
                ? "아직 앱이 없어요. 위에 만들고 싶은 것을 적어 보세요."
                : "아직 사용할 수 있는 앱이 없어요. 관리자가 앱을 배포하면 여기에 보여요."}
          </Empty>
        )}
        {appList.length > 0 && (
          <ListToolbar c={c} placeholder="앱 이름·설명으로 찾기" className="mb-3" />
        )}
        <NoMatch c={c} />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {c.pageItems.map((app) => {
            const proj = !filter && app.project_id ? byId.get(app.project_id) : undefined;
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
                  {editable && <CardMenu onMove={() => setMoving(app)} />}
                </div>
                {proj && (
                  <span className="mt-3 inline-flex max-w-full items-center gap-1.5 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                    <ProjectDot color={proj.color} className="h-2 w-2" />
                    <span className="truncate">{proj.name}</span>
                  </span>
                )}
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
        {appList.length > 0 && <ListPager c={c} className="mt-3" />}
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
      <BlankAppDialog open={open} onClose={() => setOpen(false)} projectId={projectId} />
      <ProjectDialog
        ws={ws}
        open={projectDialog !== null}
        onClose={() => setProjectDialog(null)}
        project={projectDialog === "edit" ? current : null}
        myUserId={me.data?.id}
        onSaved={(p) => setFilter(p.id)}
        onDeleted={() => setFilter("")}
      />
      <MoveProjectDialog app={moving} projects={projectList} onClose={() => setMoving(null)} />
    </PageContainer>
  );
}
