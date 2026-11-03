import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { useSignup } from "@/lib/api/auth";
import { AuthShell } from "@/pages/auth/AuthShell";
import { safeNext } from "@/lib/nav";

export default function SignupPage() {
  const [form, setForm] = useState({ name: "", email: "", password: "", workspace_name: "" });
  const signup = useSignup();
  const navigate = useNavigate();
  const [params] = useSearchParams();

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    signup.mutate(
      { ...form, workspace_name: form.workspace_name || undefined },
      { onSuccess: () => navigate(safeNext(params.get("next")), { replace: true }) },
    );
  };

  return (
    <AuthShell title="가입하기" subtitle="몇 가지만 적으면 바로 시작할 수 있어요.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="이름" htmlFor="name">
          <Input id="name" required value={form.name} onChange={set("name")} />
        </Field>
        <Field label="이메일" htmlFor="email">
          <Input id="email" type="email" required value={form.email} onChange={set("email")} />
        </Field>
        <Field label="비밀번호" htmlFor="password" hint="8자 이상으로 정해 주세요.">
          <Input
            id="password"
            type="password"
            minLength={8}
            required
            autoComplete="new-password"
            value={form.password}
            onChange={set("password")}
          />
        </Field>
        <Field
          label="팀(워크스페이스) 이름"
          htmlFor="ws"
          hint="비우면 '내 워크스페이스'로 만들어요."
        >
          <Input id="ws" value={form.workspace_name} onChange={set("workspace_name")} />
        </Field>
        <ErrorBox error={signup.error} />
        <Button type="submit" className="w-full" disabled={signup.isPending}>
          {signup.isPending ? "가입 중…" : "가입하고 시작하기"}
        </Button>
      </form>
      <p className="mt-4 text-center text-sm text-slate-500">
        이미 계정이 있나요?{" "}
        <Link to="/login" className="font-medium text-indigo-600">
          로그인
        </Link>
      </p>
    </AuthShell>
  );
}
