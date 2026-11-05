import { useState, type FormEvent } from "react";
import { PASSWORD_HINT, passwordProblem } from "@/lib/passwordRule";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { useAuthConfig, useSignup } from "@/lib/api/auth";
import { VerifyStep } from "@/pages/auth/AccountSteps";
import { AuthShell } from "@/pages/auth/AuthShell";
import { safeNext } from "@/lib/nav";
import { AgreementChecks, LegalLinks } from "@/pages/legal/AgreementChecks";

export default function SignupPage() {
  const [form, setForm] = useState({ name: "", email: "", password: "", workspace_name: "" });
  const signup = useSignup();
  const authConfig = useAuthConfig();
  const [agree, setAgree] = useState({ terms: false, privacy: false });
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // v0.7: 이메일 인증이 필요하면 가입 뒤 메일 확인 안내를 보여 준다
  const [verifyEmail, setVerifyEmail] = useState<string | null>(null);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    signup.mutate(
      {
        ...form,
        workspace_name: form.workspace_name || undefined,
        agree_terms: agree.terms,
        agree_privacy: agree.privacy,
      },
      {
        onSuccess: (r) => {
          if ("verify_required" in r) setVerifyEmail(r.email);
          else navigate(safeNext(params.get("next")), { replace: true });
        },
      },
    );
  };

  if (verifyEmail)
    return (
      <AuthShell title="거의 다 됐어요" subtitle="메일함에서 확인 링크를 열어 주세요.">
        <VerifyStep email={verifyEmail} onBack={() => navigate("/login")} />
      </AuthShell>
    );

  // 가입을 닫아 둔 곳: 계정은 관리자가 임시 비밀번호로 내준다
  if (authConfig.data && !authConfig.data.allow_signup)
    return (
      <AuthShell title="지금은 가입을 받지 않아요" subtitle="계정은 관리자가 만들어 드려요.">
        <div className="space-y-4 text-sm text-slate-600">
          <p>
            워크스페이스 관리자에게 <b>계정 만들기</b>를 요청하면 임시 비밀번호를 받을 수 있어요.
            처음 로그인할 때 새 비밀번호를 정하면 바로 쓸 수 있어요.
          </p>
          <Link to="/login" className="font-semibold text-indigo-600 hover:text-indigo-700">
            로그인 화면으로
          </Link>
        </div>
      </AuthShell>
    );

  return (
    <AuthShell title="가입하기" subtitle="몇 가지만 적으면 바로 시작할 수 있어요.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="이름" htmlFor="name">
          <Input id="name" required value={form.name} onChange={set("name")} />
        </Field>
        <Field label="이메일" htmlFor="email">
          <Input id="email" type="email" required value={form.email} onChange={set("email")} />
        </Field>
        <Field label="비밀번호" htmlFor="password" hint={PASSWORD_HINT}>
          <Input
            id="password"
            type="password"
            minLength={8}
            required
            autoComplete="new-password"
            value={form.password}
            aria-invalid={Boolean(passwordProblem(form.password))}
            onChange={set("password")}
          />
          {passwordProblem(form.password) && (
            <p className="text-xs text-amber-700">{passwordProblem(form.password)}</p>
          )}
        </Field>
        <Field
          label="팀(워크스페이스) 이름"
          htmlFor="ws"
          hint="비우면 '내 워크스페이스'로 만들어요."
        >
          <Input id="ws" value={form.workspace_name} onChange={set("workspace_name")} />
        </Field>
        <AgreementChecks value={agree} onChange={setAgree} />
        <ErrorBox error={signup.error} />
        <Button
          type="submit"
          className="w-full"
          disabled={signup.isPending || !agree.terms || !agree.privacy}
        >
          {signup.isPending ? "가입 중…" : "가입하고 시작하기"}
        </Button>
      </form>
      <p className="mt-4 text-center text-sm text-slate-500">
        이미 계정이 있나요?{" "}
        <Link to="/login" className="font-medium text-indigo-600">
          로그인
        </Link>
      </p>
      <LegalLinks />
    </AuthShell>
  );
}
