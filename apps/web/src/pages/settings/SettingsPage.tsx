// 내 설정: 프로필, 화면(테마·글자 크기), 작업 환경(기본 워크스페이스·Enter로 보내기), 비밀번호.
import { Check, KeyRound, Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { PageContainer } from "@/app/Layout";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, PageHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { HelpButton } from "@/help/HelpButton";
import { ko } from "@/i18n/ko";
import { useMe } from "@/lib/api/auth";
import type { Preferences } from "@/lib/api/types";
import { preferencesOf, useChangePassword, useUpdateMe } from "@/lib/api/v3";
import { cn } from "@/lib/cn";
import { rememberEnterToSend } from "@/lib/composer";
import { applyFontSize, applyTheme, type ThemePref } from "@/store/theme";

const THEMES: { value: ThemePref; label: string; hint: string; icon: LucideIcon }[] = [
  { value: "light", label: "밝게", hint: "언제나 밝은 화면", icon: Sun },
  { value: "dark", label: "어둡게", hint: "눈이 편한 어두운 화면", icon: Moon },
  { value: "system", label: "시스템", hint: "기기 설정을 따라가요", icon: Monitor },
];

export default function SettingsPage() {
  const me = useMe();
  const update = useUpdateMe();

  if (me.isLoading) return <Loading />;
  if (me.error || !me.data)
    return (
      <PageContainer>
        <ErrorBox error={me.error} />
      </PageContainer>
    );

  const prefs = preferencesOf(me.data);

  async function savePrefs(patch: Partial<Preferences>, done?: string) {
    // 화면에는 바로 적용하고, 서버에도 저장해 다른 기기에서도 같게 보이게 한다
    if (patch.theme) applyTheme(patch.theme);
    if (patch.font_size) applyFontSize(patch.font_size);
    if (typeof patch.enter_to_send === "boolean") rememberEnterToSend(patch.enter_to_send);
    try {
      await update.mutateAsync({ preferences: patch });
      if (done) toast.success(done);
    } catch (e) {
      toast.error(e);
    }
  }

  return (
    <PageContainer>
      <div className="mx-auto max-w-3xl">
        <PageHeader
          title="내 설정"
          description="내 계정에만 적용되는 설정이에요. 바꾸면 바로 저장돼요."
          help={<HelpButton page="mysettings" />}
        />
        <div className="space-y-5">
          <ProfileCard name={me.data.name} email={me.data.email} />

          <Card>
            <CardHeader title="화면" description="테마와 글자 크기를 고르세요." />
            <CardBody className="space-y-5">
              <div
                role="radiogroup"
                aria-label="테마"
                className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-3"
              >
                {THEMES.map((t) => (
                  <ThemeCard
                    key={t.value}
                    value={t.value}
                    label={t.label}
                    hint={t.hint}
                    icon={t.icon}
                    selected={prefs.theme === t.value}
                    onSelect={() => void savePrefs({ theme: t.value })}
                  />
                ))}
              </div>
              <div className="space-y-1.5">
                <p className="text-sm font-medium text-slate-700">글자 크기</p>
                <div role="radiogroup" aria-label="글자 크기" className="flex flex-wrap gap-2">
                  {(
                    [
                      ["normal", "보통", "text-sm"],
                      ["large", "크게", "text-base"],
                    ] as const
                  ).map(([value, label, size]) => (
                    <button
                      key={value}
                      type="button"
                      role="radio"
                      aria-checked={prefs.font_size === value}
                      onClick={() => void savePrefs({ font_size: value })}
                      className={cn(
                        "inline-flex h-10 items-center gap-2 rounded-lg border px-4 font-medium transition-colors",
                        size,
                        prefs.font_size === value
                          ? "border-indigo-400 bg-indigo-50 text-indigo-700"
                          : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
                      )}
                    >
                      가 <span className="text-xs font-normal text-slate-500">{label}</span>
                    </button>
                  ))}
                </div>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="작업 환경" />
            <CardBody className="space-y-5">
              <Field
                label="기본 워크스페이스"
                htmlFor="default-ws"
                hint="처음 들어오거나 고른 워크스페이스가 없을 때 이 워크스페이스를 열어요."
              >
                <Select
                  id="default-ws"
                  value={prefs.default_workspace_id ?? ""}
                  onChange={(e) =>
                    void savePrefs(
                      { default_workspace_id: e.target.value || null },
                      "기본 워크스페이스를 바꿨어요.",
                    )
                  }
                >
                  <option value="">정하지 않음 (마지막에 쓴 곳)</option>
                  {me.data.workspaces.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name} · {ko.roles[w.role]}
                    </option>
                  ))}
                </Select>
              </Field>
              <Toggle
                id="enter-to-send"
                checked={prefs.enter_to_send}
                onChange={(v) => void savePrefs({ enter_to_send: v })}
                label="Enter로 보내기"
                hint={
                  prefs.enter_to_send
                    ? "Enter를 누르면 보내고, Shift+Enter로 줄을 바꿔요."
                    : "Enter는 줄바꿈이에요. Ctrl+Enter(Mac은 ⌘+Enter)로 보내요."
                }
              />
            </CardBody>
          </Card>

          <PasswordCard />
        </div>
      </div>
    </PageContainer>
  );
}

function ProfileCard({ name, email }: { name: string; email: string }) {
  const [value, setValue] = useState(name);
  const update = useUpdateMe();
  useEffect(() => setValue(name), [name]);
  const changed = value.trim() !== name && value.trim().length > 0;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!changed) return;
    try {
      await update.mutateAsync({ name: value.trim() });
      toast.success("이름을 바꿨어요.");
    } catch (err) {
      toast.error(err);
    }
  }

  return (
    <Card>
      <CardHeader title="프로필" />
      <CardBody>
        <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
          <Field label="이름" htmlFor="profile-name">
            <div className="flex gap-2">
              <Input
                id="profile-name"
                value={value}
                maxLength={100}
                onChange={(e) => setValue(e.target.value)}
              />
              <Button type="submit" disabled={!changed || update.isPending}>
                저장
              </Button>
            </div>
          </Field>
          <Field label="이메일" htmlFor="profile-email" hint="로그인 아이디라서 바꿀 수 없어요.">
            <Input id="profile-email" value={email} readOnly disabled />
          </Field>
        </form>
      </CardBody>
    </Card>
  );
}

function ThemeCard({
  value,
  label,
  hint,
  icon: Icon,
  selected,
  onSelect,
}: {
  value: ThemePref;
  label: string;
  hint: string;
  icon: LucideIcon;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      aria-label={`테마 ${label}`}
      onClick={onSelect}
      className={cn(
        "group relative flex flex-col overflow-hidden rounded-xl border text-left transition",
        selected
          ? "border-indigo-500 ring-2 ring-indigo-500/30"
          : "border-slate-200 hover:border-slate-300",
      )}
    >
      <MiniPreview value={value} />
      <span className="flex items-center gap-2 px-3 py-2.5">
        <Icon className="h-4 w-4 text-slate-500" />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-slate-900">{label}</span>
          <span className="block truncate text-[11px] text-slate-500">{hint}</span>
        </span>
        {selected && (
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-600 text-white">
            <Check className="h-3 w-3" />
          </span>
        )}
      </span>
    </button>
  );
}

/** 테마 카드 위의 작은 화면 미리보기. 실제 테마와 상관없이 고정 색으로 그린다. */
function MiniPreview({ value }: { value: ThemePref }) {
  const light = {
    bg: "#f8fafc",
    side: "#ffffff",
    line: "#e2e8f0",
    card: "#ffffff",
    ink: "#cbd5e1",
  };
  const dark = { bg: "#020617", side: "#0f172a", line: "#1e293b", card: "#0f172a", ink: "#334155" };
  const pane = (c: typeof light, clip?: string): ReactNode => (
    <div className="absolute inset-0 flex" style={{ background: c.bg, clipPath: clip }} aria-hidden>
      <div
        className="w-1/4 space-y-1 p-1.5"
        style={{ background: c.side, borderRight: `1px solid ${c.line}` }}
      >
        <div className="h-1.5 w-3/4 rounded-full" style={{ background: "#6366f1" }} />
        <div className="h-1 w-full rounded-full" style={{ background: c.ink }} />
        <div className="h-1 w-2/3 rounded-full" style={{ background: c.ink }} />
      </div>
      <div className="flex flex-1 flex-col gap-1.5 p-2">
        <div className="h-1.5 w-1/2 rounded-full" style={{ background: c.ink }} />
        <div className="grid flex-1 grid-cols-2 gap-1.5">
          <div className="rounded" style={{ background: c.card, border: `1px solid ${c.line}` }} />
          <div className="rounded" style={{ background: c.card, border: `1px solid ${c.line}` }} />
        </div>
      </div>
    </div>
  );
  return (
    <div className="relative h-20 w-full border-b border-slate-200">
      {value === "light" && pane(light)}
      {value === "dark" && pane(dark)}
      {value === "system" && (
        <>
          {pane(light)}
          {pane(dark, "polygon(100% 0, 100% 100%, 0 100%)")}
        </>
      )}
    </div>
  );
}

function Toggle({
  id,
  checked,
  onChange,
  label,
  hint,
}: {
  id: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <label htmlFor={id} className="block text-sm font-medium text-slate-700">
          {label}
        </label>
        {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors",
          checked ? "bg-indigo-600" : "bg-slate-300",
        )}
      >
        <span
          className={cn(
            "inline-block h-5 w-5 rounded-full bg-white shadow transition-transform",
            checked ? "translate-x-[22px]" : "translate-x-0.5",
          )}
        />
      </button>
    </div>
  );
}

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const change = useChangePassword();
  const mismatch = confirm.length > 0 && next !== confirm;
  const tooShort = next.length > 0 && next.length < 8;
  const ready = current.length > 0 && next.length >= 8 && next === confirm;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready) return;
    try {
      await change.mutateAsync({ current_password: current, new_password: next });
      toast.success("비밀번호를 바꿨어요.");
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      toast.error(err);
    }
  }

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-1.5">
            <KeyRound className="h-4 w-4 text-slate-400" /> 비밀번호 바꾸기
          </span>
        }
      />
      <CardBody>
        <form onSubmit={submit} className="grid gap-4 sm:grid-cols-3" noValidate>
          <Field label="지금 비밀번호" htmlFor="pw-current">
            <Input
              id="pw-current"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </Field>
          <Field label="새 비밀번호" htmlFor="pw-new" hint="8자 이상">
            <Input
              id="pw-new"
              type="password"
              autoComplete="new-password"
              value={next}
              aria-invalid={tooShort}
              onChange={(e) => setNext(e.target.value)}
            />
          </Field>
          <Field label="새 비밀번호 확인" htmlFor="pw-confirm">
            <Input
              id="pw-confirm"
              type="password"
              autoComplete="new-password"
              value={confirm}
              aria-invalid={mismatch}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </Field>
          <div className="flex flex-wrap items-center gap-3 sm:col-span-3">
            <Button type="submit" disabled={!ready || change.isPending}>
              비밀번호 바꾸기
            </Button>
            {mismatch && (
              <p role="alert" className="text-sm text-red-600">
                새 비밀번호가 서로 달라요.
              </p>
            )}
            {!mismatch && tooShort && (
              <p className="text-sm text-amber-700">새 비밀번호는 8자 이상이어야 해요.</p>
            )}
          </div>
        </form>
      </CardBody>
    </Card>
  );
}
