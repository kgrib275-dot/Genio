// 관리자가 내준 임시 비밀번호로 로그인했을 때: 새 비밀번호를 정하기 전에는 다른 화면을 쓸 수 없다.
import { KeyRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { signOut } from "@/lib/api/client";
import { useChangePassword } from "@/lib/api/v3";
import { PASSWORD_HINT, passwordProblem } from "@/lib/passwordRule";
import { AuthShell } from "@/pages/auth/AuthShell";

export function ForcePasswordChange({ name }: { name?: string }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const change = useChangePassword();
  const mismatch = confirm.length > 0 && next !== confirm;
  const weak = next.length > 0 ? passwordProblem(next) : null;
  const same = next.length > 0 && next === current;
  const ready = current.length > 0 && next.length >= 8 && !weak && !same && next === confirm;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!ready) return;
    change.mutate(
      { current_password: current, new_password: next },
      { onSuccess: () => toast.success("새 비밀번호로 바꿨어요. 이제 시작해 볼까요?") },
    );
  };

  return (
    <AuthShell
      title="비밀번호를 새로 정해 주세요"
      subtitle={`${name ? `${name}님, ` : ""}관리자가 준 임시 비밀번호는 처음 한 번만 쓸 수 있어요.`}
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field label="임시 비밀번호" htmlFor="fp-current" hint="관리자에게 받은 비밀번호예요.">
          <Input
            id="fp-current"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </Field>
        <Field label="새 비밀번호" htmlFor="fp-new" hint={weak ?? PASSWORD_HINT}>
          <Input
            id="fp-new"
            type="password"
            autoComplete="new-password"
            value={next}
            aria-invalid={Boolean(weak) || same}
            onChange={(e) => setNext(e.target.value)}
          />
        </Field>
        <Field
          label="새 비밀번호 확인"
          htmlFor="fp-confirm"
          hint={
            mismatch
              ? "새 비밀번호와 같게 한 번 더 입력하세요."
              : same
                ? "임시 비밀번호와 다른 비밀번호를 정하세요."
                : undefined
          }
        >
          <Input
            id="fp-confirm"
            type="password"
            autoComplete="new-password"
            value={confirm}
            aria-invalid={mismatch}
            onChange={(e) => setConfirm(e.target.value)}
          />
        </Field>
        <ErrorBox error={change.error} />
        <Button type="submit" className="w-full" disabled={!ready || change.isPending}>
          <KeyRound className="h-4 w-4" />{" "}
          {change.isPending ? "바꾸는 중…" : "비밀번호 바꾸고 시작하기"}
        </Button>
        <button
          type="button"
          onClick={() => signOut()}
          className="block w-full text-center text-xs text-slate-500 hover:text-slate-700"
        >
          나중에 하고 로그아웃
        </button>
      </form>
    </AuthShell>
  );
}
