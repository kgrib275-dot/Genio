// v0.7 내 설정 > 보안: 이메일 확인, 2단계 인증, 로그인한 기기, 내 데이터, 탈퇴
import {
  Copy,
  Download,
  LogOut,
  MailWarning,
  Monitor,
  ShieldCheck,
  Smartphone,
  Trash2,
} from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import {
  downloadMyData,
  useDeleteAccount,
  useDisable2fa,
  useEnable2fa,
  useNewRecoveryCodes,
  useResendVerifyMe,
  useRevokeAllSessions,
  useRevokeSession,
  useSessions,
  useSetup2fa,
} from "@/lib/api/account";
import { signOut } from "@/lib/api/client";
import type { Me } from "@/lib/api/types";
import { copyText, formatDate } from "@/lib/cn";
import { deviceName } from "@/lib/deviceName";

export function EmailVerifyCard({ me }: { me: Me }) {
  const resend = useResendVerifyMe();
  if (me.email_verified !== false) return null;
  return (
    <Card>
      <CardBody className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <MailWarning className="h-6 w-6 shrink-0 text-amber-500" />
        <div className="min-w-0 flex-1 text-sm">
          <p className="font-semibold text-slate-900">이메일 확인이 아직이에요</p>
          <p className="text-slate-500">
            {me.email}으로 확인 메일을 받아 링크를 열면 비밀번호 찾기 등을 쓸 수 있어요.
          </p>
          <ErrorBox error={resend.error} />
        </div>
        <Button
          variant="outline"
          disabled={resend.isPending}
          onClick={() => resend.mutate(undefined, { onSuccess: (r) => toast.success(r.message) })}
        >
          확인 메일 보내기
        </Button>
      </CardBody>
    </Card>
  );
}

function RecoveryCodes({ codes }: { codes: string[] }) {
  return (
    <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
      <p className="text-sm font-semibold text-amber-900">
        복구 코드 10개 — 지금 한 번만 보여요. 안전한 곳에 적어 두세요.
      </p>
      <p className="text-xs text-amber-800">
        휴대폰을 잃어버렸을 때 인증 코드 대신 하나씩 쓸 수 있어요.
      </p>
      <div className="grid grid-cols-2 gap-1 font-mono text-sm text-slate-800 sm:grid-cols-5">
        {codes.map((c) => (
          <span key={c} className="rounded bg-white px-2 py-1 text-center">
            {c}
          </span>
        ))}
      </div>
      <Button
        size="sm"
        variant="outline"
        onClick={() => void copyText(codes.join("\n")).then(() => toast.success("복사했어요."))}
      >
        <Copy className="h-3.5 w-3.5" /> 모두 복사
      </Button>
    </div>
  );
}

export function TwoFactorCard({ me }: { me: Me }) {
  const setup = useSetup2fa();
  const enable = useEnable2fa();
  const disable = useDisable2fa();
  const regen = useNewRecoveryCodes();
  const [code, setCode] = useState("");
  const [pw, setPw] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const on = Boolean(me.two_factor);

  const confirm = (e: FormEvent) => {
    e.preventDefault();
    enable.mutate(code.trim(), {
      onSuccess: (r) => {
        setCodes(r.recovery_codes);
        setCode("");
        setup.reset();
        toast.success("2단계 인증을 켰어요.");
      },
    });
  };

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-indigo-500" /> 2단계 인증
            {on ? <Badge tone="green">켜짐</Badge> : <Badge>꺼짐</Badge>}
          </span>
        }
        description="비밀번호 말고도 휴대폰 인증 앱의 6자리 숫자를 한 번 더 확인해요. 관리자 계정이라면 꼭 켜 두세요."
      />
      <CardBody className="space-y-4">
        {codes && <RecoveryCodes codes={codes} />}
        {!on && !setup.data && (
          <Button onClick={() => setup.mutate()} disabled={setup.isPending}>
            <Smartphone className="h-4 w-4" /> 2단계 인증 켜기
          </Button>
        )}
        {!on && setup.data && (
          <form onSubmit={confirm} className="space-y-3 text-sm">
            <ol className="list-decimal space-y-2 pl-5 text-slate-700">
              <li>
                휴대폰에 <b>Google OTP</b>나 <b>Microsoft Authenticator</b> 같은 인증 앱을 설치해요.
              </li>
              <li>
                앱에서 &lsquo;키 직접 입력&rsquo;을 고르고 아래 키를 넣어요(휴대폰에서 이 화면을
                열었다면{" "}
                <a href={setup.data.otpauth_uri} className="font-medium text-indigo-600 underline">
                  여기를 눌러 앱에 바로 추가
                </a>
                ).
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  <code className="break-all rounded bg-slate-100 px-2 py-1 font-mono text-[13px] tracking-wider text-slate-900">
                    {setup.data.secret.replace(/(.{4})/g, "$1 ").trim()}
                  </code>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      void copyText(setup.data?.secret ?? "").then(() =>
                        toast.success("복사했어요."),
                      )
                    }
                  >
                    <Copy className="h-3.5 w-3.5" /> 복사
                  </Button>
                </div>
              </li>
              <li>앱에 나온 6자리 숫자를 넣고 확인을 눌러요.</li>
            </ol>
            <div className="flex flex-wrap gap-2">
              <Input
                aria-label="인증 코드 6자리"
                className="w-36 text-center font-mono tracking-widest"
                inputMode="numeric"
                maxLength={6}
                placeholder="123456"
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
              <Button type="submit" disabled={enable.isPending || code.trim().length !== 6}>
                확인하고 켜기
              </Button>
              <Button type="button" variant="ghost" onClick={() => setup.reset()}>
                그만두기
              </Button>
            </div>
            <ErrorBox error={enable.error} />
          </form>
        )}
        {on && (
          <div className="space-y-3 text-sm">
            <Field label="비밀번호" htmlFor="tfa-pw">
              <Input
                id="tfa-pw"
                type="password"
                autoComplete="current-password"
                value={pw}
                onChange={(e) => setPw(e.target.value)}
              />
            </Field>
            <Field label="인증 코드 또는 복구 코드(끌 때만)" htmlFor="tfa-code">
              <Input id="tfa-code" value={code} onChange={(e) => setCode(e.target.value)} />
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                disabled={!pw || regen.isPending}
                onClick={() =>
                  regen.mutate(pw, {
                    onSuccess: (r) => {
                      setCodes(r.recovery_codes);
                      setPw("");
                    },
                  })
                }
              >
                복구 코드 새로 만들기
              </Button>
              <Button
                variant="outline"
                className="text-red-600"
                disabled={!pw || !code || disable.isPending}
                onClick={() =>
                  disable.mutate(
                    { password: pw, code: code.trim() },
                    {
                      onSuccess: () => {
                        setPw("");
                        setCode("");
                        setCodes(null);
                        toast.success("2단계 인증을 껐어요.");
                      },
                    },
                  )
                }
              >
                2단계 인증 끄기
              </Button>
            </div>
            <ErrorBox error={disable.error ?? regen.error} />
          </div>
        )}
      </CardBody>
    </Card>
  );
}

export function SessionsCard() {
  const sessions = useSessions();
  const revoke = useRevokeSession();
  const revokeAll = useRevokeAllSessions();
  const list = sessions.data ?? [];
  return (
    <Card>
      <CardHeader
        title="로그인한 기기"
        description="모르는 기기가 있으면 로그아웃시키고 비밀번호를 바꾸세요."
      />
      <CardBody className="p-0">
        {sessions.isLoading && <Loading />}
        <ErrorBox error={sessions.error} />
        <ul className="divide-y divide-slate-100 border-t border-slate-100">
          {list.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-2 px-4 py-3 text-sm sm:px-5">
              <Monitor className="h-4 w-4 shrink-0 text-slate-400" />
              <div className="min-w-0 flex-1">
                <p className="font-medium text-slate-800">
                  {deviceName(s.user_agent)} {s.current && <Badge tone="green">지금 이 기기</Badge>}
                </p>
                <p className="text-xs text-slate-500">
                  {s.ip || "주소 모름"} · 마지막 사용 {formatDate(s.last_seen_at)}
                </p>
              </div>
              {!s.current && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={revoke.isPending}
                  onClick={() =>
                    revoke.mutate(s.id, {
                      onSuccess: () => toast.success("그 기기를 로그아웃시켰어요."),
                    })
                  }
                >
                  <LogOut className="h-3.5 w-3.5" /> 로그아웃
                </Button>
              )}
            </li>
          ))}
          {!sessions.isLoading && list.length === 0 && (
            <li className="px-5 py-4 text-sm text-slate-500">기록된 기기가 없어요.</li>
          )}
        </ul>
        <div className="border-t border-slate-100 px-4 py-3 sm:px-5">
          <Button
            variant="outline"
            disabled={revokeAll.isPending}
            onClick={() => {
              if (window.confirm("이 기기만 남기고 다른 모든 기기에서 로그아웃할까요?"))
                revokeAll.mutate(undefined, {
                  onSuccess: () => toast.success("다른 모든 기기에서 로그아웃했어요."),
                });
            }}
          >
            <LogOut className="h-4 w-4" /> 다른 모든 기기에서 로그아웃
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

export function MyDataCard() {
  const del = useDeleteAccount();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [pw, setPw] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Card>
      <CardHeader title="내 데이터" description="내 정보를 파일로 받거나 계정을 지워요." />
      <CardBody className="space-y-4 text-sm">
        <Button
          variant="outline"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await downloadMyData();
            } catch (err) {
              toast.error(err);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Download className="h-4 w-4" /> 내 데이터 내려받기(JSON)
        </Button>
        <p className="text-xs text-slate-500">
          프로필, 속한 워크스페이스, 내가 만든 앱 목록, 내 대화, 내 활동 기록이 들어 있어요.
          비밀값은 빠져요.
        </p>
        {!open ? (
          <button
            type="button"
            className="text-sm font-medium text-red-600 hover:text-red-700"
            onClick={() => setOpen(true)}
          >
            회원 탈퇴…
          </button>
        ) : (
          <div className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-3">
            <p className="font-semibold text-red-800">정말 탈퇴할까요?</p>
            <ul className="list-disc space-y-0.5 pl-5 text-xs text-red-800">
              <li>로그인할 수 없게 되고 모든 기기에서 로그아웃돼요. 되돌릴 수 없어요.</li>
              <li>
                내가 만든 앱·대화는 워크스페이스에 남고, 만든 사람은 '탈퇴한 사용자'로 보여요.
              </li>
              <li>
                다른 멤버가 있는 워크스페이스의 하나뿐인 소유자라면 먼저 소유권을 넘겨야 해요.
              </li>
            </ul>
            <Field label="비밀번호" htmlFor="del-pw">
              <Input
                id="del-pw"
                type="password"
                autoComplete="current-password"
                value={pw}
                onChange={(e) => setPw(e.target.value)}
              />
            </Field>
            <Field label="확인을 위해 '탈퇴'라고 적어 주세요" htmlFor="del-confirm">
              <Input
                id="del-confirm"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
              />
            </Field>
            <ErrorBox error={del.error} />
            <div className="flex gap-2">
              <Button
                className="bg-red-600 hover:bg-red-500"
                disabled={!pw || confirmText.trim() !== "탈퇴" || del.isPending}
                onClick={() =>
                  del.mutate(
                    { password: pw, confirm: confirmText.trim() },
                    {
                      onSuccess: (r) => {
                        toast.success(r.message);
                        signOut();
                        navigate("/login", { replace: true });
                      },
                    },
                  )
                }
              >
                <Trash2 className="h-4 w-4" /> 탈퇴하기
              </Button>
              <Button variant="ghost" onClick={() => setOpen(false)}>
                그만두기
              </Button>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
