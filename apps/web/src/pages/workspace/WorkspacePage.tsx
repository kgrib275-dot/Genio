import { Avatar } from "@/components/AppIcon";
import { useState, type FormEvent } from "react";
import { PageContainer } from "@/app/Layout";
import { JsonView } from "@/components/canvas/RunPanel";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Empty, PageHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { Tabs } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toast-store";
import { ko } from "@/i18n/ko";
import { ROLES, type ProviderKind, type Role } from "@/lib/api/types";
import {
  useAuditLogs,
  useCreateLlmProvider,
  useDeleteLlmProvider,
  useInvitations,
  useInvite,
  useLlmProviders,
  useMembers,
  useUpdateMemberRole,
  useUsage,
  type NewLlmProvider,
} from "@/lib/api/workspace";
import { copyText, formatCost, formatDate } from "@/lib/cn";
import { canEdit, canManage, canViewRuns, useSession } from "@/store/session";

type Tab = "members" | "llm" | "usage" | "audit";

function MembersTab({ ws, manage }: { ws: string; manage: boolean }) {
  const members = useMembers(ws);
  const update = useUpdateMemberRole(ws);
  const invitations = useInvitations(ws, manage);
  const invite = useInvite(ws);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [lastUrl, setLastUrl] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    invite.mutate(
      { email, role },
      {
        onSuccess: (inv) => {
          setEmail("");
          setLastUrl(inv.accept_url);
          toast.success("초대 링크를 만들었어요. 링크를 복사해 전달하세요.");
        },
      },
    );
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
      <Card>
        <CardHeader title="멤버" />
        <CardBody className="p-0">
          {members.isLoading && <Loading />}
          <ErrorBox error={members.error ?? update.error} />
          <ul className="divide-y divide-slate-100">
            {(members.data ?? []).map((m) => (
              <li key={m.id} className="flex items-center gap-3 px-5 py-3 text-sm">
                <Avatar name={m.name} />
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{m.name}</p>
                  <p className="truncate text-xs text-slate-500">{m.email}</p>
                </div>
                {manage ? (
                  <Select
                    aria-label={`${m.name} 역할`}
                    className="w-28 shrink-0"
                    value={m.role}
                    onChange={(e) =>
                      update.mutate(
                        { id: m.id, role: e.target.value as Role },
                        { onSuccess: () => toast.success("역할을 바꿨어요.") },
                      )
                    }
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {ko.roles[r]}
                      </option>
                    ))}
                  </Select>
                ) : (
                  <Badge>{ko.roles[m.role]}</Badge>
                )}
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>
      {manage && (
        <Card>
          <CardHeader
            title="멤버 초대"
            description="초대 링크를 받은 사람이 가입하면 멤버가 돼요."
          />
          <CardBody className="space-y-4">
            <form onSubmit={submit} className="space-y-3">
              <Field label="이메일" htmlFor="inv-email">
                <Input
                  id="inv-email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </Field>
              <Field label="역할" htmlFor="inv-role">
                <Select
                  id="inv-role"
                  value={role}
                  onChange={(e) => setRole(e.target.value as Role)}
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {ko.roles[r]}
                    </option>
                  ))}
                </Select>
              </Field>
              <ErrorBox error={invite.error} />
              <Button type="submit" disabled={invite.isPending}>
                초대 링크 만들기
              </Button>
            </form>
            {lastUrl && (
              <div className="rounded bg-slate-50 p-2 text-xs">
                <p className="mb-1 break-all">{lastUrl}</p>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={async () => {
                    if (await copyText(lastUrl)) toast.success(ko.common.copied);
                  }}
                >
                  {ko.common.copy}
                </Button>
              </div>
            )}
            {(invitations.data ?? []).length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium text-slate-500">보낸 초대</p>
                <ul className="space-y-1 text-xs">
                  {invitations.data?.map((i) => (
                    <li key={i.id} className="flex justify-between gap-2">
                      <span className="truncate">
                        {i.email} · {ko.roles[i.role]}
                      </span>
                      <span className="shrink-0 text-slate-400">
                        {i.accepted_at ? "수락함" : `~${formatDate(i.expires_at)}`}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  );
}

const PROVIDERS: { value: ProviderKind; label: string; model: string }[] = [
  { value: "anthropic", label: "Anthropic (Claude)", model: "claude-sonnet-5-5" },
  { value: "openai", label: "OpenAI", model: "gpt-4o-mini" },
  { value: "google", label: "Google (Gemini)", model: "gemini-2.0-flash" },
  { value: "openai-compatible", label: "OpenAI 호환 API", model: "" },
];

function LlmTab({ ws, manage }: { ws: string; manage: boolean }) {
  const list = useLlmProviders(ws);
  const create = useCreateLlmProvider(ws);
  const del = useDeleteLlmProvider(ws);
  const [form, setForm] = useState<NewLlmProvider>({
    provider: "anthropic",
    label: "Claude",
    api_key: "",
    base_url: "",
    default_model: "claude-sonnet-5-5",
    is_default: true,
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { ...form, base_url: form.base_url || undefined },
      {
        onSuccess: () => {
          toast.success("AI 연결을 저장했어요. 키는 암호화되어 다시 볼 수 없어요.");
          setForm({ ...form, api_key: "" });
        },
      },
    );
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
      <Card>
        <CardHeader title="AI 연결" description="빌더와 AI 응답 노드가 이 키로 모델을 불러요." />
        <CardBody className="p-0">
          {list.isLoading && <Loading />}
          <ErrorBox error={list.error} />
          {list.data?.length === 0 && (
            <p className="px-5 py-6 text-sm text-slate-500">
              아직 AI 연결이 없어요. 빌더를 쓰려면 하나 이상 등록해야 해요.
            </p>
          )}
          <ul className="divide-y divide-slate-100">
            {(list.data ?? []).map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
                <span className="font-medium">{p.label}</span>
                <Badge tone="blue">{p.provider}</Badge>
                {p.is_default && <Badge tone="green">기본</Badge>}
                <span className="text-xs text-slate-500">
                  {p.default_model} · 키 {p.api_key_masked}
                  {p.base_url && ` · ${p.base_url}`}
                </span>
                {manage && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="ml-auto text-red-600"
                    onClick={() => {
                      if (window.confirm(`'${p.label}' 연결을 지울까요?`)) del.mutate(p.id);
                    }}
                  >
                    삭제
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>
      {manage && (
        <Card>
          <CardHeader title="새 AI 연결" />
          <CardBody>
            <form onSubmit={submit} className="space-y-3">
              <Field label="제공사" htmlFor="llm-provider">
                <Select
                  id="llm-provider"
                  value={form.provider}
                  onChange={(e) => {
                    const p = PROVIDERS.find((x) => x.value === e.target.value);
                    setForm({
                      ...form,
                      provider: e.target.value as ProviderKind,
                      default_model: p?.model ?? "",
                      label: p?.label.split(" ")[0] ?? form.label,
                    });
                  }}
                >
                  {PROVIDERS.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="이름" htmlFor="llm-label">
                <Input
                  id="llm-label"
                  required
                  value={form.label}
                  onChange={(e) => setForm({ ...form, label: e.target.value })}
                />
              </Field>
              <Field label="API 키" htmlFor="llm-key">
                <Input
                  id="llm-key"
                  type="password"
                  autoComplete="off"
                  required
                  value={form.api_key}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                />
              </Field>
              <Field label="기본 모델" htmlFor="llm-model">
                <Input
                  id="llm-model"
                  required
                  value={form.default_model}
                  onChange={(e) => setForm({ ...form, default_model: e.target.value })}
                />
              </Field>
              {form.provider === "openai-compatible" && (
                <Field label="주소(base URL)" htmlFor="llm-base">
                  <Input
                    id="llm-base"
                    required
                    placeholder="https://example.com/v1"
                    value={form.base_url}
                    onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                  />
                </Field>
              )}
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.is_default}
                  onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
                />
                기본 연결로 쓰기
              </label>
              <ErrorBox error={create.error} />
              <Button type="submit" disabled={create.isPending}>
                저장
              </Button>
            </form>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

function UsageTab({ ws }: { ws: string }) {
  const usage = useUsage(ws);
  if (usage.isLoading) return <Loading />;
  if (usage.error) return <ErrorBox error={usage.error} />;
  const u = usage.data;
  if (!u) return null;
  const stats = [
    { label: "실행 수", value: u.total_runs.toLocaleString() },
    { label: "입력 토큰", value: u.total_input_tokens.toLocaleString() },
    { label: "출력 토큰", value: u.total_output_tokens.toLocaleString() },
    { label: "비용", value: formatCost(u.total_cost) },
  ];
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-4">
        {stats.map((s) => (
          <Card key={s.label} className="p-4">
            <p className="text-xs text-slate-500">{s.label}</p>
            <p className="mt-1 text-xl font-semibold">{s.value}</p>
          </Card>
        ))}
      </div>
      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500">
            <tr>
              <th className="px-4 py-2 font-medium">앱</th>
              <th className="px-4 py-2 text-right font-medium">실행</th>
              <th className="px-4 py-2 text-right font-medium">입력 토큰</th>
              <th className="px-4 py-2 text-right font-medium">출력 토큰</th>
              <th className="px-4 py-2 text-right font-medium">비용</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {u.by_app.map((a) => (
              <tr key={a.app_id}>
                <td className="px-4 py-2">{a.app_name}</td>
                <td className="px-4 py-2 text-right">{a.runs}</td>
                <td className="px-4 py-2 text-right">{a.input_tokens.toLocaleString()}</td>
                <td className="px-4 py-2 text-right">{a.output_tokens.toLocaleString()}</td>
                <td className="px-4 py-2 text-right">{formatCost(a.cost)}</td>
              </tr>
            ))}
            {u.by_app.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-slate-500">
                  아직 사용 기록이 없어요.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function AuditTab({ ws }: { ws: string }) {
  const logs = useAuditLogs(ws);
  if (logs.isLoading) return <Loading />;
  if (logs.error) return <ErrorBox error={logs.error} />;
  if (!logs.data?.length) return <Empty>아직 기록이 없어요.</Empty>;
  return (
    <Card className="overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs text-slate-500">
          <tr>
            <th className="px-4 py-2 font-medium">시간</th>
            <th className="px-4 py-2 font-medium">사람</th>
            <th className="px-4 py-2 font-medium">행동</th>
            <th className="px-4 py-2 font-medium">대상</th>
            <th className="px-4 py-2 font-medium">상세</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 align-top">
          {logs.data.map((l) => (
            <tr key={l.id}>
              <td className="whitespace-nowrap px-4 py-2 text-xs text-slate-500">
                {formatDate(l.created_at)}
              </td>
              <td className="px-4 py-2 text-xs">{l.user_email ?? "-"}</td>
              <td className="px-4 py-2 font-mono text-xs">{l.action}</td>
              <td className="px-4 py-2 text-xs">
                {l.target_type}
                {l.target_id && (
                  <span className="block text-slate-400">{l.target_id.slice(0, 8)}</span>
                )}
              </td>
              <td className="px-4 py-2">
                {Object.keys(l.meta ?? {}).length > 0 ? <JsonView value={l.meta} /> : "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

export default function WorkspacePage() {
  const { workspaceId: ws, role } = useSession();
  const manage = canManage(role);
  const tabs: { value: Tab; label: string }[] = [
    { value: "members", label: "멤버·역할" },
    ...(canEdit(role) ? [{ value: "llm" as Tab, label: "AI 연결" }] : []),
    ...(canViewRuns(role) ? [{ value: "usage" as Tab, label: "사용량" }] : []),
    ...(manage ? [{ value: "audit" as Tab, label: "활동 기록" }] : []),
  ];
  const [tab, setTab] = useState<Tab>("members");

  return (
    <PageContainer>
      <PageHeader title="워크스페이스" description="멤버와 역할, AI 연결, 사용량을 관리해요." />
      <Tabs value={tab} onChange={setTab} items={tabs} />
      {tab === "members" && <MembersTab ws={ws} manage={manage} />}
      {tab === "llm" && <LlmTab ws={ws} manage={manage} />}
      {tab === "usage" && <UsageTab ws={ws} />}
      {tab === "audit" && <AuditTab ws={ws} />}
    </PageContainer>
  );
}
