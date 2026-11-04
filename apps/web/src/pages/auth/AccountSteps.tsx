// v0.7 로그인 중간 단계: 2단계 인증 코드 입력, 이메일 확인 안내
import { KeyRound, Loader2, MailCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { useLoginMfa, useResendVerifyPublic } from "@/lib/api/account";

export function MfaStep({
  mfaToken,
  onDone,
  onBack,
}: {
  mfaToken: string;
  onDone: () => void;
  onBack: () => void;
}) {
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);
  const mfa = useLoginMfa();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    mfa.mutate({ mfa_token: mfaToken, code: code.trim() }, { onSuccess: onDone });
  };
  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="flex gap-3 rounded-xl bg-indigo-50 px-4 py-3 text-sm text-indigo-900">
        <KeyRound className="mt-0.5 h-5 w-5 shrink-0" />
        <p>
          {recovery
            ? "저장해 둔 복구 코드 하나를 넣어 주세요(예: abcd-2345). 한 번 쓴 코드는 다시 못 써요."
            : "휴대폰 인증 앱(구글 OTP 등)에 보이는 6자리 숫자를 넣어 주세요."}
        </p>
      </div>
      <input
        id="mfa-code"
        aria-label={recovery ? "복구 코드" : "인증 코드 6자리"}
        autoFocus
        autoComplete="one-time-code"
        inputMode={recovery ? "text" : "numeric"}
        maxLength={recovery ? 20 : 6}
        placeholder={recovery ? "abcd-2345" : "123456"}
        value={code}
        onChange={(e) => setCode(e.target.value)}
        className="h-12 w-full rounded-xl border border-slate-300 bg-white text-center font-mono text-xl tracking-[0.3em] text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-4 focus:ring-indigo-500/15"
      />
      <ErrorBox error={mfa.error} />
      <button
        type="submit"
        disabled={mfa.isPending || code.trim().length < 6}
        className="flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 text-[15px] font-semibold text-white hover:bg-indigo-500 disabled:opacity-60"
      >
        {mfa.isPending && <Loader2 className="h-4 w-4 animate-spin" />} 확인
      </button>
      <div className="flex justify-between text-sm">
        <button type="button" className="text-slate-500 hover:text-slate-800" onClick={onBack}>
          ← 다시 로그인
        </button>
        <button
          type="button"
          className="font-medium text-indigo-600 hover:text-indigo-700"
          onClick={() => {
            setRecovery((v) => !v);
            setCode("");
          }}
        >
          {recovery ? "인증 앱 코드로" : "휴대폰이 없어요(복구 코드)"}
        </button>
      </div>
    </form>
  );
}

export function VerifyStep({ email, onBack }: { email: string; onBack: () => void }) {
  const resend = useResendVerifyPublic();
  return (
    <div className="space-y-4">
      <div className="flex gap-3 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
        <MailCheck className="mt-0.5 h-5 w-5 shrink-0" />
        <div>
          <p className="font-semibold">이메일 확인이 필요해요</p>
          <p className="mt-0.5">
            <b>{email}</b>으로 보낸 메일의 링크를 열면 로그인할 수 있어요. 메일이 안 보이면 스팸함을
            확인하세요.
          </p>
        </div>
      </div>
      {resend.data && <p className="text-sm text-slate-600">{resend.data.message}</p>}
      <ErrorBox error={resend.error} />
      <button
        type="button"
        disabled={resend.isPending}
        onClick={() => resend.mutate(email)}
        className="flex h-11 w-full items-center justify-center rounded-xl border border-slate-300 bg-white text-[15px] font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
      >
        확인 메일 다시 보내기
      </button>
      <button
        type="button"
        className="text-sm text-slate-500 hover:text-slate-800"
        onClick={onBack}
      >
        ← 로그인으로
      </button>
    </div>
  );
}
