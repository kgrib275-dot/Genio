import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Empty, PageHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { ko } from "@/i18n/ko";
import { useApps, useCreateApp } from "@/lib/api/apps";
import { useTemplates } from "@/lib/api/resources";
import type { AppType } from "@/lib/api/types";
import { useWorkspaceRuns } from "@/lib/api/workspace";
import { formatDate } from "@/lib/cn";
import { canEdit, canViewRuns, useSession } from "@/store/session";

function CreateAppDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ws = useSession((s) => s.workspaceId);
  const templates = useTemplates(ws);
  const create = useCreateApp(ws);
  const navigate = useNavigate();
  const [form, setForm] = useState({
    name: "",
    type: "chat" as AppType,
    description: "",
    icon: "🤖",
    template_key: "",
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { ...form, template_key: form.template_key || undefined },
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
      title="새 앱 만들기"
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
        <div className="grid grid-cols-[80px_1fr] gap-3">
          <Field label="아이콘" htmlFor="icon">
            <Input
              id="icon"
              maxLength={4}
              value={form.icon}
              onChange={(e) => setForm({ ...form, icon: e.target.value })}
            />
          </Field>
          <Field label="앱 이름" htmlFor="app-name">
            <Input
              id="app-name"
              required
              placeholder="예: 고객 문의 분류기"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </Field>
        </div>
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
        <Field label="설명" htmlFor="app-desc">
          <Textarea
            id="app-desc"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </Field>
        <Field
          label="템플릿으로 시작(선택)"
          htmlFor="app-template"
          hint="마켓에서 설치한 템플릿만 보여요."
        >
          <Select
            id="app-template"
            value={form.template_key}
            onChange={(e) => setForm({ ...form, template_key: e.target.value })}
          >
            <option value="">빈 앱으로 시작</option>
            {(templates.data ?? []).map((t) => (
              <option key={t.key} value={t.key}>
                {t.name}
              </option>
            ))}
          </Select>
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

  return (
    <PageContainer>
      <PageHeader
        title="내 앱"
        description="말로 요청하면 빌더가 흐름을 만들어 줘요."
        action={editable && <Button onClick={() => setOpen(true)}>+ 새 앱 만들기</Button>}
      />
      {apps.isLoading && <Loading />}
      <ErrorBox error={apps.error} />
      {apps.data && apps.data.length === 0 && (
        <Empty>
          {editable
            ? "아직 앱이 없어요. '새 앱 만들기'로 시작해 보세요."
            : "아직 사용할 수 있는 앱이 없어요. 관리자가 앱을 배포하면 여기에 보여요."}
        </Empty>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {(apps.data ?? []).map((app) => {
          const body = (
            <Card className="h-full p-4 transition-shadow hover:shadow-md">
              <div className="flex items-start gap-3">
                <span className="text-3xl" aria-hidden>
                  {app.icon || "🤖"}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold">{app.name}</p>
                  <p className="text-xs text-slate-500">
                    {ko.appTypes[app.type]} · 버전 {app.latest_version ?? "없음"}
                  </p>
                </div>
                <StatusBadge status={app.status} />
              </div>
              {app.description && (
                <p className="mt-3 line-clamp-2 text-sm text-slate-600">{app.description}</p>
              )}
              <p className="mt-3 text-xs text-slate-400">수정 {formatDate(app.updated_at)}</p>
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

      {canViewRuns(role) && (
        <Card className="mt-8">
          <CardHeader title="최근 실행" description="모든 앱의 최근 실행 기록이에요." />
          <CardBody className="p-0">
            {runs.isLoading && <Loading />}
            {runs.data && runs.data.length === 0 && (
              <p className="px-5 py-6 text-sm text-slate-500">아직 실행 기록이 없어요.</p>
            )}
            <ul className="divide-y divide-slate-100">
              {(runs.data ?? []).slice(0, 10).map((r) => (
                <li key={r.id}>
                  <Link
                    to={`/runs/${r.id}`}
                    className="flex items-center justify-between px-5 py-3 text-sm hover:bg-slate-50"
                  >
                    <span className="truncate">
                      {r.app_name ?? "앱"} <span className="text-slate-400">· {r.trigger}</span>
                    </span>
                    <span className="flex items-center gap-3">
                      <span className="text-xs text-slate-400">{formatDate(r.created_at)}</span>
                      <StatusBadge status={r.status} />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      )}
      <CreateAppDialog open={open} onClose={() => setOpen(false)} />
    </PageContainer>
  );
}
