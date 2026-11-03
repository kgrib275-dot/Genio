import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { ko } from "@/i18n/ko";
import { useDemoAccounts, useLogin } from "@/lib/api/auth";
import { safeNext } from "@/lib/nav";
import { AuthShell } from "@/pages/auth/AuthShell";

// 한/영 키가 한글일 때 들어가는 글자(자모·완성형)
const HANGUL = /[ᄀ-ᇿ㄰-㆏가-힣]/;

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const login = useLogin();
  const demo = useDemoAccounts();
  const navigate = useNavigate();
  const koreanInPassword = HANGUL.test(password);

  // 비밀번호를 치는 동안 로그인 뒤 첫 화면 코드를 미리 받아 둔다
  useEffect(() => {
    void import("@/pages/dashboard/DashboardPage");
  }, []);
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
          {koreanInPassword && (
            <p role="alert" className="mt-1 text-xs text-amber-700">
              비밀번호에 한글이 들어가 있어요. 한/영 키를 영문으로 바꾼 뒤 다시 입력하세요.
            </p>
          )}
        </Field>
        <ErrorBox error={login.error} />
        <Button type="submit" className="w-full" disabled={login.isPending}>
          {login.isPending ? "로그인 중…" : "로그인"}
        </Button>
      </form>
      {demo.data?.enabled && (
        <div className="mt-5 rounded-md border border-slate-200 bg-slate-50 p-3">
          <p className="text-xs font-medium text-slate-600">
            데모 계정으로 둘러보기 (비밀번호 {demo.data.password})
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {demo.data.accounts.map((a) => (
              <Button
                key={a.email}
                size="sm"
                variant="outline"
                onClick={() => {
                  setEmail(a.email);
                  setPassword(demo.data?.password ?? "");
                }}
              >
                {ko.roles[a.role as keyof typeof ko.roles] ?? a.role}
              </Button>
            ))}
          </div>
        </div>
      )}
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
