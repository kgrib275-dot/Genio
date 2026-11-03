// 워크스페이스·관리 화면이 함께 쓰는 단락들. 권한에 따라 읽기 전용으로도 보여 준다.
import { Copy, Crown, KeyRound, RotateCcw, Trash2, UserMinus, UserPlus, X } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Avatar } from "@/components/AppIcon";
import { DataView } from "@/components/DataView";
import { keyLabel, valueLabel } from "@/lib/dataLabels";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { StatTile } from "@/components/charts";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Empty } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { ko } from "@/i18n/ko";
import { ROLES, type Member, type ProviderKind, type Role } from "@/lib/api/types";
import {
  useAdminApiKeys,
  useCreateAccount,
  useDeleteApiKey,
  useRemoveMember,
  useResetPassword,
  useRevokeInvitation,
  useSystemSettings,
  useTransferOwnership,
  useUpdateSystemSettings,
  useUpdateWorkspace,
  useWorkspaceInfo,
} from "@/lib/api/v2";
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
import { optionsFrom, useListControls } from "@/lib/useListControls";
import type { AuditLog } from "@/lib/api/types";
import { useSession } from "@/store/session";
import { useMe } from "@/lib/api/auth";

// ---------------- 멤버 ----------------
function CreateAccountDialog({
  ws,
  open,
  isOwner,
  onClose,
  onCreated,
}: {
  ws: string;
  open: boolean;
  isOwner: boolean;
  onClose: () => void;
  onCreated: (r: { name: string; email: string; password: string | null }) => void;
}) {
  const create = useCreateAccount(ws);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [mode, setMode] = useState<"auto" | "manual">("auto");
  const [password, setPassword] = useState("");

  useEffect(() => {
    if (open) {
      setEmail("");
      setName("");
      setRole("member");
      setMode("auto");
      setPassword("");
      create.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { email, name, role, ...(mode === "manual" ? { password } : {}) },
      {
        onSuccess: (r) =>
          onCreated({ name: r.member.name, email: r.member.email, password: r.temporary_password }),
      },
    );
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="계정 만들기"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            취소
          </Button>
          <Button type="submit" form="create-account" disabled={create.isPending}>
            {create.isPending ? "만드는 중…" : "만들기"}
          </Button>
        </>
      }
    >
      <form id="create-account" onSubmit={submit} className="space-y-3">
        <p className="text-sm text-slate-500">
          이 워크스페이스에서만 쓰는 계정을 바로 만들어요. 만든 뒤 로그인 정보를 본인에게
          전달하세요.
        </p>
        <Field label="이름" htmlFor="acc-name">
          <Input id="acc-name" required value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="이메일(로그인 아이디)" htmlFor="acc-email">
          <Input
            id="acc-email"
            required
            inputMode="email"
            autoComplete="off"
            placeholder="name@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field label="역할" htmlFor="acc-role">
          <Select id="acc-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.filter((r) => r !== "owner" || isOwner).map((r) => (
              <option key={r} value={r}>
                {ko.roles[r]}
              </option>
            ))}
          </Select>
        </Field>
        <fieldset className="space-y-1.5">
          <legend className="mb-1 text-xs font-medium text-slate-600">비밀번호</legend>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="pw-mode"
              checked={mode === "auto"}
              onChange={() => setMode("auto")}
              className="accent-indigo-600"
            />
            임시 비밀번호 자동으로 만들기(추천)
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="pw-mode"
              checked={mode === "manual"}
              onChange={() => setMode("manual")}
              className="accent-indigo-600"
            />
            직접 정하기
          </label>
          {mode === "manual" && (
            <Input
              aria-label="비밀번호 직접 입력"
              type="text"
              minLength={8}
              required
              autoComplete="new-password"
              placeholder="8자 이상"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
        </fieldset>
        <ErrorBox error={create.error} />
      </form>
    </Dialog>
  );
}

/** 새로 만든 임시 비밀번호를 한 번만 보여 준다. */
function IssuedPasswordDialog({
  issued,
  onClose,
}: {
  issued: { name: string; email: string; password: string } | null;
  onClose: () => void;
}) {
  const text = issued
    ? `제니오 로그인 정보\n주소: ${window.location.origin}/login\n이메일: ${issued.email}\n임시 비밀번호: ${issued.password}\n로그인한 뒤 내 설정에서 비밀번호를 바꿔 주세요.`
    : "";
  return (
    <Dialog
      open={issued !== null}
      onClose={onClose}
      title="임시 비밀번호"
      footer={<Button onClick={onClose}>확인했어요</Button>}
    >
      {issued && (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">
            <b>{issued.name}</b>님의 임시 비밀번호예요. 이 창을 닫으면 다시 볼 수 없어요.
          </p>
          <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
            <code className="flex-1 select-all break-all font-mono text-lg font-semibold tracking-wider text-slate-900">
              {issued.password}
            </code>
            <Button
              size="sm"
              variant="outline"
              onClick={async () => {
                if (await copyText(issued.password)) toast.success(ko.common.copied);
              }}
            >
              <Copy className="h-3.5 w-3.5" /> 복사
            </Button>
          </div>
          <Button
            variant="outline"
            className="w-full"
            onClick={async () => {
              if (await copyText(text)) toast.success("로그인 안내문을 복사했어요.");
            }}
          >
            로그인 안내문 복사(주소·이메일·비밀번호)
          </Button>
          <p className="text-xs text-slate-500">
            로그인한 뒤 <b>내 설정</b>에서 비밀번호를 바꾸도록 안내하세요.
          </p>
        </div>
      )}
    </Dialog>
  );
}

export function MembersSection({ ws, manage }: { ws: string; manage: boolean }) {
  const myRole = useSession((s) => s.role);
  const members = useMembers(ws);
  const update = useUpdateMemberRole(ws);
  const remove = useRemoveMember(ws);
  const transfer = useTransferOwnership(ws);
  const invitations = useInvitations(ws, manage);
  const revoke = useRevokeInvitation(ws);
  const invite = useInvite(ws);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [lastUrl, setLastUrl] = useState("");
  const isOwner = myRole === "owner";
  const me = useMe();
  const reset = useResetPassword(ws);
  const [creating, setCreating] = useState(false);
  const [issued, setIssued] = useState<{ name: string; email: string; password: string } | null>(
    null,
  );
  // 비밀번호 재설정: 내 계정 아님, 이 워크스페이스에만 속함, 소유자·관리자 계정은 소유자만
  const mc = useListControls(members.data, {
    key: "members",
    search: (m) => `${m.name} ${m.email}`,
    filters: [
      {
        id: "role",
        label: "역할",
        options: ROLES.map((r) => ({ value: r, label: ko.roles[r] })),
        match: (m, v) => m.role === v,
      },
    ],
  });
  const ic = useListControls(invitations.data, {
    key: "invitations",
    defaultSize: 10,
    search: (i) => i.email,
    filters: [
      {
        id: "state",
        label: "상태",
        options: [
          { value: "pending", label: "기다리는 중" },
          { value: "accepted", label: "수락함" },
        ],
        match: (i, v) => (v === "accepted") === Boolean(i.accepted_at),
      },
    ],
  });
  const canReset = (m: Member) =>
    manage &&
    m.user_id !== me.data?.id &&
    m.only_here !== false &&
    (isOwner || (m.role !== "owner" && m.role !== "admin"));

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
      <Card className="min-w-0">
        <CardHeader
          title="멤버"
          description={`${members.data?.length ?? 0}명`}
          action={
            manage ? (
              <Button size="sm" onClick={() => setCreating(true)}>
                <UserPlus className="h-4 w-4" /> 계정 만들기
              </Button>
            ) : undefined
          }
        />
        <CardBody className="p-0">
          {members.isLoading && <Loading />}
          <ErrorBox
            error={members.error ?? update.error ?? remove.error ?? transfer.error ?? reset.error}
          />
          <ListToolbar c={mc} placeholder="이름·이메일 검색" className="px-4 pb-3 sm:px-5" />
          <ul className="divide-y divide-slate-100 border-t border-slate-100">
            {mc.pageItems.map((m) => (
              <li
                key={m.id}
                className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm sm:px-5"
              >
                <Avatar name={m.name} />
                <div className="min-w-0 flex-1 basis-40">
                  <p className="font-medium">{m.name}</p>
                  <p className="truncate text-xs text-slate-500">{m.email}</p>
                </div>
                {manage && m.role !== "owner" ? (
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
                    {ROLES.filter((r) => r !== "owner" || isOwner).map((r) => (
                      <option key={r} value={r}>
                        {ko.roles[r]}
                      </option>
                    ))}
                  </Select>
                ) : (
                  <Badge tone={m.role === "owner" ? "amber" : "gray"}>
                    {m.role === "owner" && <Crown className="h-3 w-3" />}
                    {ko.roles[m.role]}
                  </Badge>
                )}
                {canReset(m) && (
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`${m.name} 비밀번호 재설정`}
                    title="비밀번호 재설정"
                    disabled={reset.isPending}
                    onClick={() => {
                      if (
                        window.confirm(
                          `${m.name}님의 비밀번호를 새 임시 비밀번호로 바꿀까요? 지금 비밀번호는 더 이상 쓸 수 없어요.`,
                        )
                      )
                        reset.mutate(m.id, {
                          onSuccess: (r) =>
                            setIssued({
                              name: m.name,
                              email: m.email,
                              password: r.temporary_password,
                            }),
                        });
                    }}
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                  </Button>
                )}
                {manage && m.role !== "owner" && (
                  <span className="flex gap-0.5">
                    {isOwner && (
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`${m.name}에게 소유권 넘기기`}
                        title="소유권 넘기기"
                        disabled={transfer.isPending}
                        onClick={() => {
                          if (
                            window.confirm(
                              `${m.name}님에게 소유권을 넘길까요? 나는 관리자가 되고, 되돌리려면 새 소유자가 다시 넘겨야 해요.`,
                            )
                          )
                            transfer.mutate(m.id, {
                              onSuccess: () => toast.success("소유권을 넘겼어요."),
                            });
                        }}
                      >
                        <Crown className="h-3.5 w-3.5" />
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-red-600"
                      aria-label={`${m.name} 내보내기`}
                      title="내보내기"
                      disabled={remove.isPending}
                      onClick={() => {
                        if (window.confirm(`${m.name}님을 워크스페이스에서 내보낼까요?`))
                          remove.mutate(m.id, { onSuccess: () => toast.success("내보냈어요.") });
                      }}
                    >
                      <UserMinus className="h-3.5 w-3.5" />
                    </Button>
                  </span>
                )}
              </li>
            ))}
          </ul>
          <NoMatch c={mc} />
          <ListPager c={mc} className="border-t border-slate-100 px-4 py-2 sm:px-5" />
        </CardBody>
      </Card>
      <CreateAccountDialog
        ws={ws}
        open={creating}
        isOwner={isOwner}
        onClose={() => setCreating(false)}
        onCreated={(r) => {
          setCreating(false);
          if (r.password) setIssued({ ...r, password: r.password });
          else toast.success(`${r.name}님 계정을 만들었어요.`);
        }}
      />
      <IssuedPasswordDialog issued={issued} onClose={() => setIssued(null)} />
      {manage && (
        <Card className="min-w-0">
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
                  {ROLES.filter((r) => r !== "owner" || isOwner).map((r) => (
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
              <div className="rounded-lg bg-slate-50 p-2 text-xs">
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
                {(invitations.data?.length ?? 0) > 5 && (
                  <ListToolbar c={ic} placeholder="이메일 검색" className="mb-2" />
                )}
                <ul className="space-y-1 text-xs">
                  {ic.pageItems.map((i) => (
                    <li key={i.id} className="flex items-center justify-between gap-2">
                      <span className="min-w-0 truncate">
                        {i.email} · {ko.roles[i.role]}
                      </span>
                      <span className="flex shrink-0 items-center gap-1 text-slate-400">
                        {i.accepted_at ? "수락함" : `~${formatDate(i.expires_at)}`}
                        {!i.accepted_at && (
                          <button
                            type="button"
                            aria-label={`${i.email} 초대 취소`}
                            title="초대 취소"
                            className="rounded p-0.5 hover:bg-slate-100 hover:text-red-600"
                            onClick={() =>
                              revoke.mutate(i.id, {
                                onSuccess: () => toast.success("초대를 취소했어요."),
                                onError: (err) => toast.error(err),
                              })
                            }
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
                <NoMatch c={ic} />
                {ic.total > 10 && <ListPager c={ic} className="mt-2" />}
              </div>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  );
}

// ---------------- AI 모델 ----------------
const PROVIDERS: { value: ProviderKind; label: string; model: string }[] = [
  { value: "anthropic", label: "Anthropic (Claude)", model: "claude-sonnet-5-5" },
  { value: "openai", label: "OpenAI", model: "gpt-4o-mini" },
  { value: "google", label: "Google (Gemini)", model: "gemini-2.0-flash" },
  { value: "openai-compatible", label: "OpenAI 호환 API", model: "" },
];

function DefaultModels({ ws }: { ws: string }) {
  const info = useWorkspaceInfo(ws);
  const providers = useLlmProviders(ws);
  const update = useUpdateWorkspace(ws);
  const current = info.data?.settings?.default_models ?? {};
  const [chat, setChat] = useState("");
  const [embedding, setEmbedding] = useState("");
  useEffect(() => {
    setChat(current.chat ?? "");
    setEmbedding(current.embedding ?? "");
  }, [current.chat, current.embedding]);
  const list = providers.data ?? [];
  if (!list.length) return null;
  return (
    <Card>
      <CardHeader
        title="기본 모델"
        description="노드에서 'AI 연결'을 기본으로 둔 경우와 문서 임베딩에 쓸 연결이에요."
      />
      <CardBody className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="대화·생성" htmlFor="dm-chat">
            <Select id="dm-chat" value={chat} onChange={(e) => setChat(e.target.value)}>
              <option value="">기본 연결 따르기</option>
              {list.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label} · {p.default_model}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="문서 임베딩" htmlFor="dm-emb" hint="OpenAI 계열만 임베딩을 만들 수 있어요.">
            <Select id="dm-emb" value={embedding} onChange={(e) => setEmbedding(e.target.value)}>
              <option value="">자동(OpenAI 연결)</option>
              {list
                .filter((p) => p.provider === "openai" || p.provider === "openai-compatible")
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
            </Select>
          </Field>
        </div>
        <ErrorBox error={update.error} />
        <Button
          size="sm"
          disabled={update.isPending}
          onClick={() =>
            update.mutate(
              {
                settings: {
                  ...(info.data?.settings ?? {}),
                  default_models: { chat: chat || null, embedding: embedding || null },
                },
              },
              { onSuccess: () => toast.success("기본 모델을 저장했어요.") },
            )
          }
        >
          저장
        </Button>
      </CardBody>
    </Card>
  );
}

export function LlmSection({
  ws,
  manage,
  showDefaults = false,
}: {
  ws: string;
  manage: boolean;
  showDefaults?: boolean;
}) {
  const list = useLlmProviders(ws);
  const pc = useListControls(list.data, {
    key: "llm-providers",
    search: (p) => `${p.label} ${p.provider} ${p.default_model ?? ""}`,
    filters: [
      {
        id: "provider",
        label: "AI 서비스",
        options: optionsFrom(list.data, (p) => p.provider),
        match: (p, v) => p.provider === v,
      },
    ],
  });
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
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <Card className="min-w-0">
          <CardHeader title="AI 연결" description="빌더와 AI 노드가 이 키로 모델을 불러요." />
          <CardBody className="p-0">
            {list.isLoading && <Loading />}
            <ErrorBox error={list.error} />
            {list.data?.length === 0 && (
              <p className="px-5 py-6 text-sm text-slate-500">
                아직 AI 연결이 없어요. 빌더를 쓰려면 하나 이상 등록해야 해요.
              </p>
            )}
            {(list.data?.length ?? 0) > 0 && (
              <ListToolbar c={pc} placeholder="이름·모델 검색" className="px-4 pb-3 sm:px-5" />
            )}
            <ul className="divide-y divide-slate-100 border-t border-slate-100">
              {pc.pageItems.map((p) => (
                <li
                  key={p.id}
                  className="flex flex-wrap items-center gap-2 px-4 py-3 text-sm sm:px-5"
                >
                  <span className="font-medium">{p.label}</span>
                  <Badge tone="blue">{p.provider}</Badge>
                  {p.is_default && <Badge tone="green">기본</Badge>}
                  <span className="basis-full text-xs text-slate-500 sm:basis-auto">
                    {p.default_model} · 키 {p.api_key_masked}
                    {p.base_url && ` · ${p.base_url}`}
                  </span>
                  {manage && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="ml-auto text-red-600"
                      aria-label={`${p.label} 연결 삭제`}
                      onClick={() => {
                        if (window.confirm(`'${p.label}' 연결을 지울까요?`)) del.mutate(p.id);
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
            <NoMatch c={pc} />
            {(list.data?.length ?? 0) > 0 && (
              <ListPager c={pc} className="border-t border-slate-100 px-4 py-2 sm:px-5" />
            )}
          </CardBody>
        </Card>
        {manage && (
          <Card className="min-w-0">
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
      {showDefaults && manage && <DefaultModels ws={ws} />}
    </div>
  );
}

// ---------------- 사용량 ----------------
export function UsageSection({ ws }: { ws: string }) {
  const usage = useUsage(ws);
  const uc = useListControls(usage.data?.by_app, {
    key: "usage",
    search: (a) => a.app_name,
  });
  if (usage.isLoading) return <Loading />;
  if (usage.error) return <ErrorBox error={usage.error} />;
  const u = usage.data;
  if (!u) return null;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="실행 수" value={u.total_runs.toLocaleString()} />
        <StatTile label="입력 토큰" value={u.total_input_tokens.toLocaleString()} />
        <StatTile label="출력 토큰" value={u.total_output_tokens.toLocaleString()} />
        <StatTile label="비용" value={formatCost(u.total_cost)} />
      </div>
      {u.by_app.length === 0 ? (
        <Empty>아직 사용 기록이 없어요.</Empty>
      ) : (
        <div className="space-y-3">
          <ListToolbar c={uc} placeholder="앱 이름 검색" />
          <Card className="overflow-hidden">
            <div className="hidden grid-cols-[1fr_repeat(4,6rem)] gap-2 bg-slate-50 px-4 py-2 text-xs font-medium text-slate-500 md:grid">
              <span>앱</span>
              <span className="text-right">실행</span>
              <span className="text-right">입력 토큰</span>
              <span className="text-right">출력 토큰</span>
              <span className="text-right">비용</span>
            </div>
            <ul className="divide-y divide-slate-100">
              {uc.pageItems.map((a) => (
                <li
                  key={a.app_id}
                  className="grid grid-cols-2 gap-x-2 gap-y-0.5 px-4 py-2.5 text-sm md:grid-cols-[1fr_repeat(4,6rem)]"
                >
                  <span className="col-span-2 font-medium md:col-span-1">{a.app_name}</span>
                  <span className="text-xs text-slate-500 md:text-right md:text-sm md:text-slate-700">
                    <span className="md:hidden">실행 </span>
                    {a.runs}
                  </span>
                  <span className="text-xs text-slate-500 md:text-right md:text-sm md:text-slate-700">
                    <span className="md:hidden">입력 </span>
                    {a.input_tokens.toLocaleString()}
                  </span>
                  <span className="text-xs text-slate-500 md:text-right md:text-sm md:text-slate-700">
                    <span className="md:hidden">출력 </span>
                    {a.output_tokens.toLocaleString()}
                  </span>
                  <span className="text-xs text-slate-500 md:text-right md:text-sm md:text-slate-700">
                    <span className="md:hidden">비용 </span>
                    {formatCost(a.cost)}
                  </span>
                </li>
              ))}
            </ul>
            <NoMatch c={uc} />
          </Card>
          <ListPager c={uc} />
        </div>
      )}
    </div>
  );
}

// ---------------- 활동 기록 ----------------
/** 활동 이름을 쉬운 말로 */
const ACTION_LABELS: Record<string, string> = {
  "annotation.create": "모범 답변 추가",
  "annotation.delete": "모범 답변 삭제",
  "api_key.create": "API 키 만들기",
  "api_key.delete": "API 키 삭제",
  "app.create": "앱 만들기",
  "app.delete": "앱 삭제",
  "app.deploy": "앱 배포",
  "app.duplicate": "앱 복제",
  "app.env_vars": "앱 환경 값 변경",
  "app.features": "앱 기능 설정 변경",
  "app.import": "앱 가져오기",
  "app.undeploy": "배포 중지",
  "app.update": "앱 정보 변경",
  "app.version_restore": "버전 되돌리기",
  "app.version_save": "버전 저장",
  "auth.password_change": "비밀번호 변경",
  "auth.signup": "가입",
  "credential.create": "연결 정보 추가",
  "credential.delete": "연결 정보 삭제",
  "kb.create": "지식베이스 만들기",
  "kb.delete": "지식베이스 삭제",
  "kb.document_delete": "문서 삭제",
  "kb.document_upload": "문서 올리기",
  "kb.document_url": "웹 문서 가져오기",
  "kb.update": "지식베이스 설정 변경",
  "llm_provider.create": "AI 연결 추가",
  "llm_provider.delete": "AI 연결 삭제",
  "market.install": "마켓 설치",
  "market.uninstall": "마켓 제거",
  "member.account_create": "계정 만들기",
  "member.invite": "멤버 초대",
  "member.invite_revoke": "초대 취소",
  "member.join": "멤버 합류",
  "member.password_reset": "비밀번호 재설정",
  "member.remove": "멤버 내보내기",
  "member.role_change": "역할 변경",
  "project.create": "프로젝트 만들기",
  "project.delete": "프로젝트 삭제",
  "project.members": "프로젝트 구성원 변경",
  "project.update": "프로젝트 변경",
  "run.approve": "실행 승인 처리",
  "system.update": "시스템 설정 변경",
  "workspace.transfer_ownership": "소유권 넘기기",
  "workspace.update": "워크스페이스 설정 변경",
};

const AREA_LABELS: Record<string, string> = {
  app: "앱",
  annotation: "앱",
  api_key: "API 키",
  auth: "계정",
  credential: "연결 정보",
  kb: "지식베이스",
  llm_provider: "AI 모델",
  market: "마켓",
  member: "멤버",
  project: "프로젝트",
  run: "실행",
  system: "시스템",
  workspace: "워크스페이스",
};

const TARGET_LABELS: Record<string, string> = {
  app: "앱",
  membership: "멤버",
  invitation: "초대",
  kb: "지식베이스",
  knowledge_base: "지식베이스",
  document: "문서",
  project: "프로젝트",
  run: "실행",
  api_key: "API 키",
  credential: "연결 정보",
  llm_provider: "AI 연결",
  market_item: "마켓 아이템",
  workspace: "워크스페이스",
  system: "시스템",
  annotation: "모범 답변",
  user: "사용자",
};

const actionLabel = (a: string) => ACTION_LABELS[a] ?? a;
const areaOf = (a: string) => a.split(".")[0] ?? a;
const AREA_TONE: Record<string, string> = {
  app: "bg-indigo-50 text-indigo-700",
  annotation: "bg-indigo-50 text-indigo-700",
  member: "bg-violet-50 text-violet-700",
  auth: "bg-violet-50 text-violet-700",
  kb: "bg-emerald-50 text-emerald-700",
  project: "bg-sky-50 text-sky-700",
  api_key: "bg-amber-50 text-amber-700",
  credential: "bg-amber-50 text-amber-700",
  llm_provider: "bg-amber-50 text-amber-700",
  system: "bg-rose-50 text-rose-700",
  workspace: "bg-rose-50 text-rose-700",
};

function metaText(v: unknown, people?: Map<string, string>): string {
  if (v === null || v === undefined) return "없음";
  if (typeof v === "boolean") return v ? "예" : "아니오";
  if (typeof v === "string") return people?.get(v) ?? ko.roles[v as Role] ?? valueLabel(v);
  if (typeof v === "number") return v.toLocaleString();
  return "";
}

/** 세부 내용: 단순 값은 '이름: 값' 칩으로, 복잡하면 펼쳐 보는 목록으로 */
function AuditMeta({
  meta,
  people,
}: {
  meta: Record<string, unknown>;
  people: Map<string, string>;
}) {
  const [open, setOpen] = useState(false);
  const entries = Object.entries(meta ?? {});
  if (entries.length === 0) return <span className="text-slate-300">-</span>;
  const simple = entries.filter(([, v]) => metaText(v) !== "");
  const complex = entries.filter(([, v]) => metaText(v) === "");
  return (
    <div className="flex flex-wrap items-center gap-1">
      {simple.map(([k, v]) => (
        <span
          key={k}
          className="inline-flex max-w-full items-center gap-1 rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px]"
        >
          <span className="text-slate-500">{keyLabel(k)}</span>
          <span className="truncate font-medium text-slate-800">{metaText(v, people)}</span>
        </span>
      ))}
      {complex.length > 0 && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="text-[11px] font-medium text-indigo-600 hover:underline"
        >
          {open ? "접기" : `자세히 (${complex.length})`}
        </button>
      )}
      {open && <DataView value={Object.fromEntries(complex)} className="mt-1 w-full" />}
    </div>
  );
}

const PERIODS = [
  { value: "1", label: "오늘" },
  { value: "7", label: "최근 7일" },
  { value: "30", label: "최근 30일" },
];

function withinDays(iso: string, days: number): boolean {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - (days - 1));
  return new Date(iso).getTime() >= start.getTime();
}

export function AuditSection({ ws }: { ws: string }) {
  const logs = useAuditLogs(ws);
  const members = useMembers(ws);
  // 기록 안의 사용자 id를 이름으로
  const people = new Map((members.data ?? []).map((m) => [m.user_id, `${m.name} (${m.email})`]));
  const lc = useListControls<AuditLog>(logs.data, {
    key: "audit",
    search: (l) =>
      `${actionLabel(l.action)} ${l.action} ${l.user_email ?? ""} ${l.target_type} ${l.target_id ?? ""} ${JSON.stringify(l.meta ?? {})}`,
    filters: [
      {
        id: "area",
        label: "종류",
        options: optionsFrom(
          logs.data,
          (l) => areaOf(l.action),
          (a) => AREA_LABELS[a] ?? a,
        ),
        match: (l, v) => areaOf(l.action) === v,
      },
      {
        id: "action",
        label: "한 일",
        options: optionsFrom(logs.data, (l) => l.action, actionLabel),
        match: (l, v) => l.action === v,
      },
      {
        id: "user",
        label: "사람",
        options: optionsFrom(logs.data, (l) => l.user_email ?? "(시스템)"),
        match: (l, v) => (l.user_email ?? "(시스템)") === v,
      },
      {
        id: "period",
        label: "기간",
        options: PERIODS,
        match: (l, v) => withinDays(l.created_at, Number(v)),
      },
    ],
  });
  if (logs.isLoading) return <Loading />;
  if (logs.error) return <ErrorBox error={logs.error} />;
  if (!logs.data?.length) return <Empty>아직 기록이 없어요.</Empty>;
  return (
    <div className="space-y-3">
      <ListToolbar c={lc} placeholder="한 일·사람·내용 검색" />
      <Card className="overflow-hidden">
        <div className="hidden grid-cols-[9.5rem_11rem_10rem_minmax(0,1fr)] gap-3 bg-slate-50 px-4 py-2 text-xs font-medium text-slate-500 lg:grid">
          <span>때</span>
          <span>누가</span>
          <span>한 일</span>
          <span>대상 · 세부 내용</span>
        </div>
        <ul className="divide-y divide-slate-100">
          {lc.pageItems.map((l) => (
            <li
              key={l.id}
              className="grid gap-x-3 gap-y-1 px-4 py-2.5 text-sm lg:grid-cols-[9.5rem_11rem_10rem_minmax(0,1fr)] lg:items-start"
            >
              <span className="order-3 text-xs tabular-nums text-slate-500 lg:order-none lg:pt-0.5">
                {new Date(l.created_at).toLocaleString("ko-KR", {
                  month: "numeric",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
              <span className="order-2 truncate text-xs text-slate-600 lg:order-none lg:pt-0.5">
                {l.user_email ?? "시스템"}
              </span>
              <span className="order-1 lg:order-none">
                <span
                  className={`inline-flex rounded-md px-1.5 py-0.5 text-xs font-medium ${AREA_TONE[areaOf(l.action)] ?? "bg-slate-100 text-slate-700"}`}
                  title={l.action}
                >
                  {actionLabel(l.action)}
                </span>
              </span>
              <div className="order-4 min-w-0 space-y-1 lg:order-none">
                {(l.target_type || l.target_id) && (
                  <p className="text-xs text-slate-500">
                    {TARGET_LABELS[l.target_type] ?? l.target_type}
                    {l.target_id && (
                      <span className="ml-1 text-slate-400" title={l.target_id}>
                        {l.target_id.length > 24 ? `${l.target_id.slice(0, 8)}…` : l.target_id}
                      </span>
                    )}
                  </p>
                )}
                <AuditMeta meta={l.meta} people={people} />
              </div>
            </li>
          ))}
        </ul>
        <NoMatch c={lc} />
      </Card>
      <ListPager c={lc} />
    </div>
  );
}

// ---------------- 전체 API 키 ----------------
export function AdminApiKeysSection({ ws }: { ws: string }) {
  const keys = useAdminApiKeys(ws);
  const del = useDeleteApiKey();
  const kc = useListControls(keys.data, {
    key: "admin-api-keys",
    search: (k) => `${k.name} ${k.prefix} ${k.app_name ?? ""}`,
    filters: [
      {
        id: "app",
        label: "앱",
        options: optionsFrom(keys.data, (k) => k.app_name ?? null),
        match: (k, v) => k.app_name === v,
      },
      {
        id: "used",
        label: "사용",
        options: [
          { value: "used", label: "쓴 적 있음" },
          { value: "never", label: "한 번도 안 씀" },
        ],
        match: (k, v) => (v === "used") === Boolean(k.last_used_at),
      },
    ],
  });
  if (keys.isLoading) return <Loading />;
  if (keys.error) return <ErrorBox error={keys.error} />;
  if (!keys.data?.length)
    return <Empty>아직 만든 API 키가 없어요. 앱의 API 탭에서 만들어요.</Empty>;
  return (
    <div className="space-y-3">
      <ListToolbar c={kc} placeholder="키 이름·앱 검색" />
      <Card className="overflow-hidden">
        <ul className="divide-y divide-slate-100">
          {kc.pageItems.map((k) => (
            <li key={k.id} className="flex flex-wrap items-center gap-2 px-4 py-3 text-sm">
              <KeyRound className="h-4 w-4 text-slate-400" />
              <span className="font-medium">{k.name}</span>
              <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{k.prefix}…</code>
              {k.app_id && (
                <Link
                  to={`/apps/${k.app_id}/api`}
                  className="text-xs text-indigo-600 hover:underline"
                >
                  {k.app_name ?? "앱"}
                </Link>
              )}
              <span className="basis-full text-xs text-slate-400 sm:basis-auto">
                만든 날 {formatDate(k.created_at)} · 마지막 사용{" "}
                {k.last_used_at ? formatDate(k.last_used_at) : "없음"}
              </span>
              <Button
                size="sm"
                variant="ghost"
                className="ml-auto text-red-600"
                aria-label={`${k.name} 키 지우기`}
                onClick={() => {
                  if (window.confirm(`'${k.name}' 키를 지울까요?`))
                    del.mutate(k.id, { onError: (err) => toast.error(err) });
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </li>
          ))}
        </ul>
        <NoMatch c={kc} />
      </Card>
      <ListPager c={kc} />
    </div>
  );
}

// ---------------- 시스템 설정 ----------------
function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${checked ? "bg-indigo-600" : "bg-slate-300"}`}
    >
      <span
        className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-5" : "translate-x-0.5"}`}
      />
    </button>
  );
}

export function SystemSection({ ws }: { ws: string }) {
  const sys = useSystemSettings();
  const updateSys = useUpdateSystemSettings();
  const info = useWorkspaceInfo(ws);
  const updateWs = useUpdateWorkspace(ws);
  const [name, setName] = useState("");
  const [rate, setRate] = useState(30);
  useEffect(() => {
    if (info.data) {
      setName(info.data.name);
      setRate(info.data.settings?.public_rate_limit_per_minute ?? 30);
    }
  }, [info.data]);
  const canSys = Boolean(sys.data?.is_instance_admin);

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader title="워크스페이스" description="이름과 공개 챗 속도 제한을 정해요." />
        <CardBody className="space-y-3">
          {info.isLoading && <Loading />}
          <ErrorBox error={info.error ?? updateWs.error} />
          <Field label="이름" htmlFor="ws-name">
            <Input id="ws-name" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field
            label="공개 챗 속도 제한(분당, IP마다)"
            htmlFor="ws-rate"
            hint="한 사람이 1분에 보낼 수 있는 질문 수예요."
          >
            <Input
              id="ws-rate"
              type="number"
              min={1}
              max={600}
              value={rate}
              onChange={(e) => setRate(Math.max(1, Math.min(600, Number(e.target.value) || 30)))}
            />
          </Field>
          <Button
            size="sm"
            disabled={updateWs.isPending || !name.trim()}
            onClick={() =>
              updateWs.mutate(
                {
                  name,
                  settings: { ...(info.data?.settings ?? {}), public_rate_limit_per_minute: rate },
                },
                { onSuccess: () => toast.success("저장했어요.") },
              )
            }
          >
            저장
          </Button>
        </CardBody>
      </Card>
      <Card>
        <CardHeader
          title="시스템"
          description={
            canSys
              ? "이 서버 전체에 적용돼요."
              : "가장 먼저 만든 워크스페이스의 소유자만 바꿀 수 있어요."
          }
        />
        <CardBody className="space-y-4">
          {sys.isLoading && <Loading />}
          <ErrorBox error={sys.error ?? updateSys.error} />
          {sys.data && (
            <>
              <div className="flex items-start gap-3">
                <div className="flex-1">
                  <p className="text-sm font-medium">회원가입 허용</p>
                  <p className="text-xs text-slate-500">
                    끄면 초대받은 사람만 계정을 만들 수 있어요. 인터넷에 공개했다면 끄는 게
                    안전해요.
                  </p>
                </div>
                <Switch
                  label="회원가입 허용"
                  checked={sys.data.allow_signup}
                  disabled={!canSys || updateSys.isPending}
                  onChange={(v) => updateSys.mutate({ allow_signup: v })}
                />
              </div>
            </>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
