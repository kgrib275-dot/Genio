// v0.7 로그인 전 화면: 비밀번호 찾기 → 메일 링크로 새 비밀번호 정하기, 이메일 확인 링크
import { CheckCircle2, Loader2, Mail } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { useForgotPassword, useResetPassword, useVerifyEmail } from "@/lib/api/account";
import { PASSWORD_HINT, passwordProblem } from "@/lib/passwordRule";
import { AuthShell } from "@/pages/auth/AuthShell";

function Done({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-4">
      <div className="flex gap-3 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
        <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0" />
        <div>
          <p className="font-semibold">{title}</p>
          <div className="mt-0.5">{children}</div>
        </div>
      </div>
      <Link
        to="/login"
        className="flex h-11 w-full items-center justify-center rounded-xl bg-indigo-600 text-[15px] font-semibold text-white hover:bg-indigo-500"
      >
        로그인하러 가기
      </Link>
    </div>
  );
}

export function ForgotPasswordPage() {
  const [params] = useSearchParams();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const forgot = useForgotPassword();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    forgot.mutate(email);
  };
  return (
    <AuthShell
      title="비밀번호 찾기"
      subtitle="가입한 이메일을 넣으면 새 비밀번호를 정하는 링크를 보내 드려요."
    >
      {forgot.data ? (
        <Done title="메일을 보냈어요">
          <p>{forgot.data.message}</p>
          {forgot.data.hint && <p className="mt-1 text-xs opacity-80">{forgot.data.hint}</p>}
        </Done>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Field label="이메일" htmlFor="forgot-email">
            <Input
              id="forgot-email"
              type="email"
              required
              autoFocus
              autoComplete="email"
              placeholder="name@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <ErrorBox error={forgot.error} />
          <Button type="submit" className="w-full" disabled={forgot.isPending}>
            {forgot.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Mail className="h-4 w-4" />
            )}
            링크 보내기
          </Button>
          <p className="text-center text-sm">
            <Link to="/login" className="text-slate-500 hover:text-slate-800">
              ← 로그인으로
            </Link>
          </p>
        </form>
      )}
    </AuthShell>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const reset = useResetPassword();
  const problem = pw ? passwordProblem(pw) : null;
  const mismatch = pw2 !== "" && pw !== pw2;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (problem || mismatch) return;
    reset.mutate({ token, password: pw });
  };
  if (!token)
    return (
      <AuthShell title="링크가 올바르지 않아요" subtitle="메일에 있는 링크를 그대로 열어 주세요.">
        <Link to="/forgot-password" className="text-sm font-medium text-indigo-600">
          비밀번호 찾기 다시 하기
        </Link>
      </AuthShell>
    );
  return (
    <AuthShell title="새 비밀번호 정하기" subtitle="정하고 나면 다른 기기의 로그인은 모두 끊겨요.">
      {reset.data ? (
        <Done title="비밀번호를 바꿨어요">{reset.data.message}</Done>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <Field label="새 비밀번호" htmlFor="new-pw" hint={problem ?? PASSWORD_HINT}>
            <Input
              id="new-pw"
              type="password"
              required
              autoFocus
              autoComplete="new-password"
              value={pw}
              onChange={(e) => setPw(e.target.value)}
            />
          </Field>
          <Field
            label="한 번 더"
            htmlFor="new-pw2"
            hint={mismatch ? "두 비밀번호가 달라요." : undefined}
          >
            <Input
              id="new-pw2"
              type="password"
              required
              autoComplete="new-password"
              value={pw2}
              onChange={(e) => setPw2(e.target.value)}
            />
          </Field>
          <ErrorBox error={reset.error} />
          {reset.isError && (
            <Link to="/forgot-password" className="block text-sm font-medium text-indigo-600">
              새 링크 받기
            </Link>
          )}
          <Button
            type="submit"
            className="w-full"
            disabled={reset.isPending || Boolean(problem) || mismatch || !pw2}
          >
            비밀번호 바꾸기
          </Button>
        </form>
      )}
    </AuthShell>
  );
}

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const verify = useVerifyEmail();
  const sent = useRef(false);
  useEffect(() => {
    if (token && !sent.current) {
      sent.current = true;
      verify.mutate(token);
    }
  }, [token, verify]);
  return (
    <AuthShell title="이메일 확인" subtitle="가입한 이메일 주소를 확인하고 있어요.">
      {verify.data ? (
        <Done title="확인됐어요">{verify.data.message}</Done>
      ) : verify.isError || !token ? (
        <div className="space-y-3">
          <ErrorBox error={verify.error ?? new Error("링크가 올바르지 않아요.")} />
          <Link to="/login" className="text-sm font-medium text-indigo-600">
            로그인 화면에서 확인 메일 다시 받기
          </Link>
        </div>
      ) : (
        <p className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" /> 확인하는 중…
        </p>
      )}
    </AuthShell>
  );
}
