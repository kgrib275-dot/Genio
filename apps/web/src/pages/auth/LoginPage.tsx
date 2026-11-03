import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { useLogin } from "@/lib/api/auth";
import { safeNext } from "@/lib/nav";
import { AuthShell } from "@/pages/auth/AuthShell";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const login = useLogin();
  const navigate = useNavigate();
  const [params] = useSearchParams();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate(
      { email, password },
      { onSuccess: () => navigate(safeNext(params.get("next")), { replace: true }) },
    );
  };

  return (
    <AuthShell title="로그인">
      <form onSubmit={submit} className="space-y-4">
        <Field label="이메일" htmlFor="email">
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field label="비밀번호" htmlFor="password">
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <ErrorBox error={login.error} />
        <Button type="submit" className="w-full" disabled={login.isPending}>
          {login.isPending ? "로그인 중…" : "로그인"}
        </Button>
      </form>
      <p className="mt-4 text-center text-sm text-slate-500">
        처음이신가요?{" "}
        <Link
          to={`/signup${params.get("next") ? `?next=${encodeURIComponent(params.get("next") ?? "")}` : ""}`}
          className="font-medium text-indigo-600"
        >
          가입하기
        </Link>
      </p>
    </AuthShell>
  );
}
