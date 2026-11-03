import { Copy, Download, GitCompare, Palette, RotateCcw, UserCheck } from "lucide-react";
import { VersionDiffView } from "@/components/VersionDiffView";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { JsonView } from "@/components/canvas/RunPanel";
import { AppearanceEditor } from "@/components/chat/AppearanceEditor";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { ko } from "@/i18n/ko";
import {
  fetchVersion,
  useApp,
  useDeleteApp,
  useDeleteDeployment,
  useDeployments,
  useUpdateApp,
  useVersions,
} from "@/lib/api/apps";
import {
  ROLES,
  type Access,
  type AppType,
  type Channel,
  type Role,
  type VersionDetail,
} from "@/lib/api/types";
import { exportApp, useDuplicateApp, useRestoreVersion } from "@/lib/api/v2";
import { copyText, downloadJson, formatDate } from "@/lib/cn";
import { useListControls } from "@/lib/useListControls";
import type { DeploymentV4 } from "@/lib/api/chat";
import { useProjects } from "@/lib/api/v3";
import {
  useCreateDeploymentWithUsers,
  useUpdateDeploymentAccess,
  type DeploymentWithUsers,
} from "@/lib/api/v5a";
import { useMembers } from "@/lib/api/workspace";
import { canEdit, useSession } from "@/store/session";
import { AppNav } from "@/pages/apps/AppNav";

const CHANNEL_LABEL: Record<Channel, string> = {
  share_link: "공유 링크",
  web_widget: "웹사이트 위젯",
  api: "API",
};

const ACCESS_LABEL: Record<Access, string> = {
  workspace: "우리 워크스페이스 멤버",
  roles: "정한 역할·사람만",
  public: "누구나(로그인 없이)",
};

function CopyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="mt-2">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <div className="mt-0.5 flex gap-2">
        <code className="flex-1 overflow-x-auto whitespace-pre rounded bg-slate-50 px-2 py-1.5 text-xs">
          {value}
        </code>
        <Button
          size="sm"
          variant="outline"
          onClick={async () => {
            if (await copyText(value)) toast.success(ko.common.copied);
          }}
        >
          {ko.common.copy}
        </Button>
      </div>
    </div>
  );
}

/** 배포 대상: 역할 + 특정 사람(둘 중 하나만 맞아도 쓸 수 있음) */
function AudiencePicker({
  roles,
  onRoles,
  users,
  onUsers,
}: {
  roles: Role[];
  onRoles: (r: Role[]) => void;
  users: string[];
  onUsers: (u: string[]) => void;
}) {
  const ws = useSession((s) => s.workspaceId);
  const members = useMembers(ws);
  const [q, setQ] = useState("");
  const list = (members.data ?? []).filter((m) =>
    `${m.name} ${m.email}`.toLowerCase().includes(q.trim().toLowerCase()),
  );
  return (
    <div className="space-y-3">
      <fieldset>
        <legend className="text-sm font-medium text-slate-700">허용할 역할</legend>
        <div className="mt-1 flex flex-wrap gap-3">
          {ROLES.map((r) => (
            <label key={r} className="flex items-center gap-1 text-sm">
              <input
                type="checkbox"
                checked={roles.includes(r)}
                onChange={(e) =>
                  onRoles(e.target.checked ? [...roles, r] : roles.filter((x) => x !== r))
                }
              />
              {ko.roles[r]}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend className="text-sm font-medium text-slate-700">
          허용할 사람 <span className="font-normal text-slate-400">({users.length}명 고름)</span>
        </legend>
        <Input
          className="mt-1"
          aria-label="사람 찾기"
          placeholder="이름·이메일로 찾기"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <ul className="mt-1 max-h-40 overflow-y-auto rounded-md border border-slate-200 bg-white">
          {list.map((m) => (
            <li key={m.user_id}>
              <label className="flex cursor-pointer items-center gap-2 px-2.5 py-1.5 text-sm hover:bg-slate-50">
                <input
                  type="checkbox"
                  checked={users.includes(m.user_id)}
                  onChange={(e) =>
                    onUsers(
                      e.target.checked
                        ? [...users, m.user_id]
                        : users.filter((x) => x !== m.user_id),
                    )
                  }
                />
                <span className="min-w-0 flex-1 truncate">{m.name}</span>
                <span className="truncate text-xs text-slate-400">{m.email}</span>
              </label>
            </li>
          ))}
          {members.data && list.length === 0 && (
            <li className="px-2.5 py-2 text-xs text-slate-400">찾는 사람이 없어요.</li>
          )}
        </ul>
        <p className="mt-1 text-xs text-slate-500">
          고른 역할이거나 고른 사람이면 쓸 수 있어요. 소유자는 늘 쓸 수 있어요.
        </p>
      </fieldset>
    </div>
  );
}

function AccessEditor({
  appId,
  dep,
  onClose,
}: {
  appId: string;
  dep: DeploymentWithUsers;
  onClose: () => void;
}) {
  const update = useUpdateDeploymentAccess(appId);
  const [roles, setRoles] = useState<Role[]>(dep.allowed_roles ?? []);
  const [users, setUsers] = useState<string[]>(dep.allowed_users ?? []);
  return (
    <div className="mt-3 space-y-2 rounded-md bg-slate-50 p-3">
      <AudiencePicker roles={roles} onRoles={setRoles} users={users} onUsers={setUsers} />
      <ErrorBox error={update.error} />
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="outline" onClick={onClose}>
          취소
        </Button>
        <Button
          size="sm"
          disabled={update.isPending}
          onClick={() =>
            update.mutate(
              { id: dep.id, access: "roles", allowed_roles: roles, allowed_users: users },
              {
                onSuccess: () => {
                  toast.success("쓸 수 있는 사람을 바꿨어요.");
                  onClose();
                },
              },
            )
          }
        >
          저장
        </Button>
      </div>
    </div>
  );
}

function DeploymentsCard({ appId, editable }: { appId: string; editable: boolean }) {
  const deployments = useDeployments(appId);
  const appInfo = useApp(appId);
  const [styling, setStyling] = useState<string | null>(null);
  const dc = useListControls(deployments.data, {
    key: "app-deployments",
    defaultSize: 10,
    search: (d) =>
      [CHANNEL_LABEL[d.channel], `버전 ${d.version}`, d.share_url ?? "", d.api_url ?? ""].join(" "),
    filters: [
      {
        id: "channel",
        label: "방식",
        options: (Object.keys(CHANNEL_LABEL) as Channel[]).map((c) => ({
          value: c,
          label: CHANNEL_LABEL[c],
        })),
        match: (d, v) => d.channel === v,
      },
      {
        id: "access",
        label: "공개 범위",
        options: (Object.keys(ACCESS_LABEL) as Access[]).map((a) => ({
          value: a,
          label: ACCESS_LABEL[a],
        })),
        match: (d, v) => d.access === v,
      },
    ],
  });
  const versions = useVersions(appId);
  const create = useCreateDeploymentWithUsers(appId);
  const [editingAccess, setEditingAccess] = useState<string | null>(null);
  const [users, setUsers] = useState<string[]>([]);
  const remove = useDeleteDeployment(appId);
  const [channel, setChannel] = useState<Channel>("share_link");
  const [access, setAccess] = useState<Access>("workspace");
  const [roles, setRoles] = useState<Role[]>(["member"]);
  const [version, setVersion] = useState<string>("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      {
        channel,
        access,
        allowed_roles: access === "roles" ? roles : undefined,
        allowed_users: access === "roles" ? users : undefined,
        version: version ? Number(version) : undefined,
      },
      { onSuccess: () => toast.success("배포했어요.") },
    );
  };

  return (
    <Card>
      <CardHeader title="배포" description="저장한 버전을 링크·위젯·API로 내보내요." />
      <CardBody className="space-y-4">
        {editable && (
          <form onSubmit={submit} className="grid gap-3 rounded-md bg-slate-50 p-3 md:grid-cols-2">
            <Field label="배포 방식" htmlFor="dep-channel">
              <Select
                id="dep-channel"
                value={channel}
                onChange={(e) => setChannel(e.target.value as Channel)}
              >
                {(Object.keys(CHANNEL_LABEL) as Channel[]).map((c) => (
                  <option key={c} value={c}>
                    {CHANNEL_LABEL[c]}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="버전" htmlFor="dep-version" hint="비우면 가장 최근 버전">
              <Select id="dep-version" value={version} onChange={(e) => setVersion(e.target.value)}>
                <option value="">최신 버전</option>
                {(versions.data ?? []).map((v) => (
                  <option key={v.id} value={v.version}>
                    버전 {v.version} {v.note && `· ${v.note}`}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="누가 쓸 수 있나요" htmlFor="dep-access">
              <Select
                id="dep-access"
                value={access}
                onChange={(e) => setAccess(e.target.value as Access)}
              >
                {(Object.keys(ACCESS_LABEL) as Access[]).map((a) => (
                  <option key={a} value={a}>
                    {ACCESS_LABEL[a]}
                  </option>
                ))}
              </Select>
            </Field>
            {access === "roles" && (
              <div className="md:col-span-2">
                <AudiencePicker roles={roles} onRoles={setRoles} users={users} onUsers={setUsers} />
              </div>
            )}
            <div className="md:col-span-2">
              <ErrorBox error={create.error} />
              <Button type="submit" className="mt-2" disabled={create.isPending}>
                배포하기
              </Button>
            </div>
          </form>
        )}
        {deployments.isLoading && <Loading />}
        {deployments.data?.length === 0 && (
          <p className="text-sm text-slate-500">
            아직 배포가 없어요. 먼저 &apos;버전 저장&apos;을 한 뒤 배포하세요.
          </p>
        )}
        {(deployments.data?.length ?? 0) > 0 && (
          <ListToolbar c={dc} placeholder="링크·주소로 찾기" />
        )}
        <NoMatch c={dc} />
        {dc.pageItems.map((d) => (
          <div key={d.id} className="rounded-md border border-slate-200 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="indigo">{CHANNEL_LABEL[d.channel]}</Badge>
              <Badge>버전 {d.version}</Badge>
              <span className="text-sm text-slate-600">
                {ACCESS_LABEL[d.access]}
                {d.access === "roles" &&
                  ` (${[
                    ...d.allowed_roles.map((r) => ko.roles[r]),
                    ...((d as DeploymentWithUsers).allowed_users?.length
                      ? [`${(d as DeploymentWithUsers).allowed_users?.length}명`]
                      : []),
                  ].join(", ")})`}
              </span>
              <span className="ml-auto text-xs text-slate-400">{formatDate(d.created_at)}</span>
              {editable && d.access === "roles" && (
                <Button
                  size="sm"
                  variant="ghost"
                  aria-expanded={editingAccess === d.id}
                  onClick={() => setEditingAccess(editingAccess === d.id ? null : d.id)}
                >
                  <UserCheck className="h-3.5 w-3.5" /> 쓸 수 있는 사람
                </Button>
              )}
              {editable && d.channel !== "api" && (
                <Button
                  size="sm"
                  variant="ghost"
                  aria-expanded={styling === d.id}
                  onClick={() => setStyling(styling === d.id ? null : d.id)}
                >
                  <Palette className="h-3.5 w-3.5" /> 모양 바꾸기
                </Button>
              )}
              {editable && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-red-600"
                  onClick={() => {
                    if (window.confirm("이 배포를 내릴까요? 링크로 더 이상 쓸 수 없게 돼요.")) {
                      remove.mutate(d.id);
                    }
                  }}
                >
                  배포 내리기
                </Button>
              )}
            </div>
            {d.channel === "share_link" && <CopyRow label="공유 링크" value={d.share_url} />}
            {d.channel === "web_widget" && (
              <>
                <CopyRow label="웹사이트에 붙일 코드" value={d.widget_snippet} />
                <CopyRow label="미리보기 링크" value={d.share_url} />
              </>
            )}
            {d.channel === "api" && <CopyRow label="API 주소(POST, SSE)" value={d.api_url} />}
            {editingAccess === d.id && (
              <AccessEditor
                appId={appId}
                dep={d as DeploymentWithUsers}
                onClose={() => setEditingAccess(null)}
              />
            )}
            {styling === d.id && (
              <AppearanceEditor
                appId={appId}
                deploymentId={d.id}
                initial={(d as DeploymentV4).appearance}
                widget={d.channel === "web_widget"}
                appName={appInfo.data?.name ?? "앱"}
                onClose={() => setStyling(null)}
              />
            )}
          </div>
        ))}
        {(deployments.data?.length ?? 0) > 0 && <ListPager c={dc} />}
      </CardBody>
    </Card>
  );
}

function VersionsCard({ appId, editable }: { appId: string; editable: boolean }) {
  const versions = useVersions(appId);
  const restore = useRestoreVersion(appId);
  const [shown, setShown] = useState<VersionDetail | null>(null);
  const [cmp, setCmp] = useState<{ from: string; to: string } | null>(null);
  const vc = useListControls(versions.data, {
    key: "app-versions",
    defaultSize: 10,
    search: (v) => `버전 ${v.version} ${v.note ?? ""}`,
  });
  return (
    <Card>
      <CardHeader
        title="버전"
        description="'버전 저장'을 할 때마다 쌓여요. 배포는 버전을 가리켜요."
      />
      <CardBody className="p-0">
        {versions.isLoading && <Loading />}
        {versions.data?.length === 0 && (
          <p className="px-5 py-4 text-sm text-slate-500">아직 저장한 버전이 없어요.</p>
        )}
        {(versions.data?.length ?? 0) > 0 && (
          <ListToolbar c={vc} placeholder="버전 번호·메모로 찾기" className="px-4 pb-3 sm:px-5" />
        )}
        <NoMatch c={vc} />
        <ul className="divide-y divide-slate-100 border-t border-slate-100 empty:hidden">
          {vc.pageItems.map((v) => (
            <li
              key={v.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm sm:px-5"
            >
              <Badge tone="indigo">버전 {v.version}</Badge>
              <span className="min-w-0 flex-1 truncate text-slate-600">
                {v.note || "메모 없음"}
              </span>
              <span className="text-xs text-slate-400">{formatDate(v.created_at)}</span>
              {editable && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={restore.isPending}
                  onClick={() => {
                    if (
                      window.confirm(
                        `작업본을 버전 ${v.version}으로 되돌릴까요? 지금 작업본의 바뀐 내용은 사라져요.`,
                      )
                    )
                      restore.mutate(v.version, {
                        onSuccess: () => toast.success(`버전 ${v.version}으로 되돌렸어요.`),
                        onError: (err) => toast.error(err),
                      });
                  }}
                >
                  <RotateCcw className="h-3.5 w-3.5" /> 되돌리기
                </Button>
              )}
              <Button
                size="sm"
                variant="ghost"
                onClick={async () => {
                  try {
                    setShown(await fetchVersion(appId, v.version));
                  } catch (err) {
                    toast.error(err);
                  }
                }}
              >
                내용 보기
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setShown(null);
                  setCmp({ from: String(v.version), to: "draft" });
                }}
              >
                <GitCompare className="h-3.5 w-3.5" /> 비교
              </Button>
            </li>
          ))}
        </ul>
        {(versions.data?.length ?? 0) > 0 && (
          <ListPager c={vc} className="border-t border-slate-100 px-4 py-2 sm:px-5" />
        )}
        {cmp && (
          <VersionDiffView
            appId={appId}
            versions={(versions.data ?? []).map((x) => x.version)}
            from={cmp.from}
            to={cmp.to}
            onChange={(from, to) => setCmp({ from, to })}
            onClose={() => setCmp(null)}
          />
        )}
        {shown && (
          <div className="border-t border-slate-100 px-5 py-3">
            <div className="mb-1 flex items-center justify-between">
              <p className="text-sm font-medium">버전 {shown.version} 그래프</p>
              <button
                type="button"
                className="text-xs text-slate-500"
                onClick={() => setShown(null)}
              >
                닫기
              </button>
            </div>
            <JsonView value={shown.graph} />
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function AppInfoCard({ appId, editable }: { appId: string; editable: boolean }) {
  const app = useApp(appId);
  const update = useUpdateApp(appId);
  const del = useDeleteApp();
  const duplicate = useDuplicateApp();
  const navigate = useNavigate();
  const ws = useSession((s) => s.workspaceId);
  const projects = useProjects(ws);
  const [form, setForm] = useState({
    name: "",
    description: "",
    icon: "",
    type: "chat" as AppType,
    project_id: "",
  });

  useEffect(() => {
    if (app.data)
      setForm({
        name: app.data.name,
        description: app.data.description,
        icon: app.data.icon,
        type: app.data.type,
        project_id: app.data.project_id ?? "",
      });
  }, [app.data]);

  return (
    <Card>
      <CardHeader title="앱 정보" />
      <CardBody>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            update.mutate(form, { onSuccess: () => toast.success("저장했어요.") });
          }}
        >
          <div className="grid grid-cols-[80px_1fr] gap-3">
            <Field label="아이콘" htmlFor="info-icon">
              <Input
                id="info-icon"
                disabled={!editable}
                value={form.icon}
                onChange={(e) => setForm({ ...form, icon: e.target.value })}
              />
            </Field>
            <Field label="이름" htmlFor="info-name">
              <Input
                id="info-name"
                disabled={!editable}
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </Field>
          </div>
          <Field label="종류" htmlFor="info-type">
            <Select
              id="info-type"
              disabled={!editable}
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
          <Field
            label="프로젝트"
            htmlFor="info-project"
            hint="저장하면 앱이 고른 프로젝트로 옮겨져요."
          >
            <Select
              id="info-project"
              disabled={!editable}
              value={form.project_id}
              onChange={(e) => setForm({ ...form, project_id: e.target.value })}
            >
              <option value="">프로젝트 없음</option>
              {(projects.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="설명" htmlFor="info-desc">
            <Textarea
              id="info-desc"
              disabled={!editable}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </Field>
          <ErrorBox error={update.error ?? del.error} />
          {editable && (
            <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-3">
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  try {
                    const data = await exportApp(appId);
                    downloadJson(`${app.data?.name ?? "app"}.genio.json`, data);
                  } catch (err) {
                    toast.error(err);
                  }
                }}
              >
                <Download className="h-3.5 w-3.5" /> 내보내기
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={duplicate.isPending}
                onClick={() =>
                  duplicate.mutate(appId, {
                    onSuccess: (copy) => {
                      toast.success("복제했어요.");
                      navigate(`/apps/${copy.id}/builder`);
                    },
                    onError: (err) => toast.error(err),
                  })
                }
              >
                <Copy className="h-3.5 w-3.5" /> 복제
              </Button>
            </div>
          )}
          {editable && (
            <div className="flex justify-between">
              <Button type="submit" disabled={update.isPending}>
                {ko.common.save}
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  if (window.confirm("앱을 지울까요? 버전·실행 기록·배포도 함께 지워져요.")) {
                    del.mutate(appId, { onSuccess: () => navigate("/") });
                  }
                }}
              >
                앱 삭제
              </Button>
            </div>
          )}
        </form>
      </CardBody>
    </Card>
  );
}

export default function AppSettingsPage() {
  const { id: appId = "" } = useParams();
  const role = useSession((s) => s.role);
  const app = useApp(appId);
  const editable = canEdit(role);
  if (app.isLoading) return <Loading />;
  if (app.error)
    return (
      <div className="p-8">
        <ErrorBox error={app.error} />
      </div>
    );
  return (
    <div>
      <AppNav appId={appId} title={app.data?.name ?? ""} icon={app.data?.icon} help="settings" />
      <div className="mx-auto grid max-w-6xl gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[3fr_2fr] lg:px-8">
        <div className="min-w-0 space-y-6">
          <DeploymentsCard appId={appId} editable={editable} />
          <VersionsCard appId={appId} editable={editable} />
        </div>
        <AppInfoCard appId={appId} editable={editable} />
      </div>
    </div>
  );
}
