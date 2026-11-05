import { ArrowRight, Check, Eye, EyeOff, Loader2, Lock, Mail } from "lucide-react";
import {
  useEffect,
  useState,
  type FormEvent,
  type InputHTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ErrorBox } from "@/components/ErrorBox";
import { useAuthConfig, useLogin } from "@/lib/api/auth";
import { cn } from "@/lib/cn";
import { safeNext } from "@/lib/nav";
import { MfaStep, VerifyStep } from "@/pages/auth/AccountSteps";
import { AuthShell } from "@/pages/auth/AuthShell";
import { LegalLinks } from "@/pages/legal/AgreementChecks";

// 한/영 키가 한글일 때 들어가는 글자(자모·완성형)
const HANGUL = /[ᄀ-ᇿ㄰-㆏가-힣]/;
const REMEMBER_KEY = "genio.login.email";

function readRemembered(): string {
  try {
    return window.localStorage.getItem(REMEMBER_KEY) ?? "";
  } catch {
    return "";
  }
}

function saveRemembered(email: string | null) {
  try {
    if (email) window.localStorage.setItem(REMEMBER_KEY, email);
    else window.localStorage.removeItem(REMEMBER_KEY);
  } catch {
    // 기억하지 못해도 로그인에는 문제없다
  }
}

/** 아이콘이 들어간 입력칸. 포커스되면 테두리와 아이콘 색이 바뀐다. */
function IconInput({
  icon,
  right,
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & {
  icon: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className="group relative">
      <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 transition-colors group-focus-within:text-indigo-500">
        {icon}
      </span>
      <input
        {...props}
        className={cn(
          "h-11 w-full rounded-xl border border-slate-300 bg-white pl-10 pr-3 text-[15px] text-slate-900 transition-all placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-4 focus:ring-indigo-500/15",
          right ? "pr-11" : "",
          className,
        )}
      />
      {right && <span className="absolute right-1.5 top-1/2 -translate-y-1/2">{right}</span>}
    </div>
  );
}

export default function LoginPage() {
  const [email, setEmail] = useState(readRemembered);
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(() => readRemembered() !== "");
  const [showPw, setShowPw] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [shake, setShake] = useState(0);
  const [success, setSuccess] = useState(false);
  // v0.7: 비밀번호 다음 단계(2단계 인증 코드 / 이메일 확인)
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [verifyEmail, setVerifyEmail] = useState<string | null>(null);
  const login = useLogin();
  const authConfig = useAuthConfig();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const koreanInPassword = HANGUL.test(password);

  // 비밀번호를 치는 동안 로그인 뒤 첫 화면 코드를 미리 받아 둔다
  useEffect(() => {
    void import("@/pages/dashboard/DashboardPage");
  }, []);

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    setCapsLock(e.getModifierState?.("CapsLock") ?? false);
  };

  function finish() {
    setSuccess(true);
    // 성공 표시를 잠깐 보여 준 뒤 이동
    window.setTimeout(() => navigate(safeNext(params.get("next")), { replace: true }), 350);
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate(
      { email, password },
      {
        onSuccess: (result) => {
          saveRemembered(remember ? email.trim() : null);
          if ("mfa_required" in result) {
            setMfaToken(result.mfa_token);
            return;
          }
          if ("verify_required" in result) {
            setVerifyEmail(result.email);
            return;
          }
          finish();
        },
        onError: () => {
          setShake((v) => v + 1);
          setPassword("");
          // 흔들린 뒤(폼이 다시 그려진 뒤) 비밀번호 칸으로
          window.setTimeout(() => document.getElementById("password")?.focus(), 0);
        },
      },
    );
  };

  const busy = login.isPending || success;
  const back = () => {
    setMfaToken(null);
    setVerifyEmail(null);
    setPassword("");
  };
  if (mfaToken)
    return (
      <AuthShell title="2단계 인증" subtitle="한 번 더 확인할게요.">
        <MfaStep mfaToken={mfaToken} onDone={finish} onBack={back} />
      </AuthShell>
    );
  if (verifyEmail)
    return (
      <AuthShell title="메일을 확인해 주세요" subtitle="가입한 이메일 주소가 맞는지 확인해요.">
        <VerifyStep email={verifyEmail} onBack={back} />
      </AuthShell>
    );
  return (
    <AuthShell title="다시 오신 걸 환영해요" subtitle="이메일과 비밀번호로 로그인하세요.">
      <form key={shake} onSubmit={submit} className={cn("space-y-4", shake > 0 && "genio-shake")}>
        <div>
          <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-slate-700">
            이메일
          </label>
          <IconInput
            id="email"
            type="email"
            autoComplete="email"
            placeholder="name@company.com"
            required
            autoFocus={!email}
            icon={<Mail className="h-[18px] w-[18px]" />}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-slate-700">
            비밀번호
          </label>
          <IconInput
            id="password"
            type={showPw ? "text" : "password"}
            autoComplete="current-password"
            required
            autoFocus={Boolean(email)}
            icon={<Lock className="h-[18px] w-[18px]" />}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={onKey}
            onKeyUp={onKey}
            onBlur={() => setCapsLock(false)}
            right={
              <button
                type="button"
                onClick={() => setShowPw((v) => !v)}
                aria-label={showPw ? "비밀번호 숨기기" : "비밀번호 보기"}
                aria-pressed={showPw}
                className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
              >
                {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            }
          />
          {koreanInPassword && (
            <p role="alert" className="genio-rise mt-1.5 text-xs text-amber-700">
              비밀번호에 한글이 들어가 있어요. 한/영 키를 영문으로 바꾼 뒤 다시 입력하세요.
            </p>
          )}
          {capsLock && !koreanInPassword && (
            <p role="status" className="genio-rise mt-1.5 text-xs text-amber-700">
              Caps Lock이 켜져 있어요. 대문자로 입력되고 있어요.
            </p>
          )}
        </div>
        <div className="flex items-center justify-between gap-2">
          <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300 accent-indigo-600"
            />
            이메일 기억하기
          </label>
          <Link
            to={`/forgot-password${email ? `?email=${encodeURIComponent(email.trim())}` : ""}`}
            className="text-sm font-medium text-indigo-600 hover:text-indigo-700"
          >
            비밀번호를 잊으셨나요?
          </Link>
        </div>
        <ErrorBox error={login.error} />
        <button
          type="submit"
          disabled={busy}
          className={cn(
            "group relative flex h-11 w-full items-center justify-center gap-2 overflow-hidden rounded-xl text-[15px] font-semibold text-white shadow-md transition-all",
            success
              ? "bg-emerald-500"
              : "bg-gradient-to-r from-indigo-600 to-violet-600 hover:-translate-y-0.5 hover:shadow-lg active:translate-y-0",
            "disabled:cursor-default",
          )}
        >
          <span className="genio-sheen pointer-events-none absolute inset-y-0 -left-1/2 w-1/3 skew-x-[-20deg] bg-white/25" />
          {success ? (
            <>
              <Check className="h-5 w-5" /> 로그인했어요
            </>
          ) : login.isPending ? (
            <>
              <Loader2 className="h-5 w-5 animate-spin" /> 확인하는 중…
            </>
          ) : (
            <>
              로그인
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </>
          )}
        </button>
      </form>
      {authConfig.data?.allow_signup ? (
        <p className="mt-5 text-center text-sm text-slate-500">
          처음이신가요?{" "}
          <Link
            to={`/signup${params.get("next") ? `?next=${encodeURIComponent(params.get("next") ?? "")}` : ""}`}
            className="font-semibold text-indigo-600 hover:text-indigo-700"
          >
            가입하기
          </Link>
        </p>
      ) : (
        <p className="mt-5 text-center text-sm text-slate-500">
          계정은 관리자가 만들어 드려요. 임시 비밀번호를 받아 로그인하세요.
        </p>
      )}
      <p className="mt-2 text-center text-xs text-slate-400">
        비밀번호를 잊었거나 메일을 받을 수 없다면 워크스페이스 관리자에게 임시 비밀번호를
        요청하세요.
      </p>
      <LegalLinks />
    </AuthShell>
  );
}
