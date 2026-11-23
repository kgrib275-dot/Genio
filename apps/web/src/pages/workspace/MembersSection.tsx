// sections.tsx에서 분리한 구간: MembersSection
import {
  Copy,
  ArrowRightLeft,
  Crown,
  RotateCcw,
  ShieldOff,
  UserMinus,
  UserPlus,
  X,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "@/lib/api/client";
import { Avatar } from "@/components/AppIcon";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { ko } from "@/i18n/ko";
import { TransferAssetsDialog } from "@/pages/workspace/TransferAssetsDialog";
import { ROLES, type Member, type Role } from "@/lib/api/types";
import {
  useCreateAccount,
  useRemoveMember,
  useResetPassword,
  useRevokeInvitation,
  useTransferOwnership,
} from "@/lib/api/v2";
import { useInvitations, useInvite, useMembers, useUpdateMemberRole } from "@/lib/api/workspace";
import { useResetMember2fa } from "@/lib/api/account";
import { copyText, formatDate } from "@/lib/cn";
import { useListControls } from "@/lib/useListControls";
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

/** 멤버 줄의 비어 있는 동작 버튼 자리(버튼과 같은 폭) */
function ActionSlot() {
  return <span aria-hidden className="inline-block h-8 w-[38px] shrink-0" />;
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
    ? `제니오 로그인 정보\n주소: ${window.location.origin}/login\n이메일: ${issued.email}\n임시 비밀번호: ${issued.password}\n처음 로그인할 때 새 비밀번호를 정하게 돼요.`
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
            처음 로그인하면 이 비밀번호를 <b>새 비밀번호로 바꾸는 화면</b>이 먼저 나와요. 임시
            비밀번호는 그 한 번만 쓸 수 있어요.
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
  const qc = useQueryClient();
  const transfer = useTransferOwnership(ws);
  /** 내보내기 전에: 이 사람이 만든 앱·키·예약이 있으면 먼저 넘기자고 안내한다 */
  const askRemove = async (m: Member) => {
    let owned = 0;
    try {
      const a = await qc.fetchQuery({
        queryKey: ["member-assets", ws, m.user_id],
        queryFn: () =>
          api.get<{
            apps: unknown[];
            api_keys: number;
            triggers: number;
            data_tables: number;
            credentials: number;
          }>(`/workspaces/${ws}/members/${m.user_id}/assets`),
        staleTime: 0,
      });
      owned = a.apps.length + a.api_keys + a.triggers + a.data_tables + a.credentials;
    } catch {
      owned = 0; // 확인하지 못해도 내보내기 자체는 막지 않는다
    }
    if (
      owned > 0 &&
      window.confirm(
        `${m.name}님이 만든 앱·표·키·예약이 ${owned}개 있어요. 내보내면 이어서 관리할 사람이 없어요.

먼저 다른 사람에게 넘길까요? (확인을 누르면 넘기기 창이 열려요)`,
      )
    ) {
      setHandover(m);
      return;
    }
    if (window.confirm(`${m.name}님을 워크스페이스에서 내보낼까요?`))
      remove.mutate(m.id, { onSuccess: () => toast.success("내보냈어요.") });
  };
  const invitations = useInvitations(ws, manage);
  const revoke = useRevokeInvitation(ws);
  const invite = useInvite(ws);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [lastUrl, setLastUrl] = useState("");
  const [handover, setHandover] = useState<Member | null>(null);
  const isOwner = myRole === "owner";
  const me = useMe();
  const reset = useResetPassword(ws);
  const reset2fa = useResetMember2fa(ws);
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
                {/* 동작 버튼은 자리를 고정해, 버튼이 없는 줄도 역할 칸이 같은 위치에 오게 한다 */}
                <div className="flex shrink-0 items-center justify-end gap-0.5">
                  {canReset(m) ? (
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
                  ) : manage ? (
                    <ActionSlot />
                  ) : null}
                  {manage && m.two_factor && m.user_id !== me.data?.id ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`${m.name} 2단계 인증 끄기`}
                      title="2단계 인증 끄기(휴대폰 분실)"
                      disabled={reset2fa.isPending}
                      onClick={() => {
                        if (
                          window.confirm(
                            `${m.name}님의 2단계 인증을 끌까요? 휴대폰을 잃어버렸을 때만 쓰세요. 다음 로그인부터 비밀번호만 확인해요.`,
                          )
                        )
                          reset2fa.mutate(m.id, {
                            onSuccess: () =>
                              toast.success(
                                "2단계 인증을 껐어요. 본인에게 다시 켜도록 안내하세요.",
                              ),
                            onError: (err) => toast.error(err),
                          });
                      }}
                    >
                      <ShieldOff className="h-3.5 w-3.5" />
                    </Button>
                  ) : manage ? (
                    <ActionSlot />
                  ) : null}
                  {manage && m.role !== "owner" ? (
                    <>
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
                        aria-label={`${m.name}이 만든 앱 넘기기`}
                        title="만든 앱·키·예약 넘기기"
                        onClick={() => setHandover(m)}
                      >
                        <ArrowRightLeft className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-red-600"
                        aria-label={`${m.name} 내보내기`}
                        title="내보내기"
                        disabled={remove.isPending}
                        onClick={() => void askRemove(m)}
                      >
                        <UserMinus className="h-3.5 w-3.5" />
                      </Button>
                    </>
                  ) : manage ? (
                    <>
                      {isOwner && <ActionSlot />}
                      <ActionSlot />
                      <ActionSlot />
                    </>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
          <NoMatch c={mc} />
          <ListPager c={mc} className="border-t border-slate-100 px-4 py-2 sm:px-5" />
        </CardBody>
      </Card>
      {handover && (
        <TransferAssetsDialog
          ws={ws}
          from={handover}
          members={members.data ?? []}
          onClose={() => setHandover(null)}
        />
      )}
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
