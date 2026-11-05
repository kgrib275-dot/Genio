// AI 연결 한 줄 아래에 펼치는 '키 관리': 키 여러 개를 두고 나눠 쓰거나, 한도에 걸리면 다음 키로 넘어가요.
import { ChevronDown, ChevronRight, KeyRound, PlugZap, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import type { LlmProvider } from "@/lib/api/types";
import {
  asProviderV9,
  useAddLlmKey,
  useDeleteLlmKey,
  usePatchLlmKey,
  usePatchLlmProvider,
  useTestLlmKey,
  type KeyView,
} from "@/lib/api/v9llm";
import type { LlmProbe } from "@/lib/api/workspace";
import { STRATEGIES, cooldownText, strategyLabel } from "@/lib/llmChain";

const WEIGHTS = Array.from({ length: 10 }, (_, i) => i + 1);

function KeyRow({
  k,
  manage,
  weighted,
  probe,
  busy,
  onPatch,
  onDelete,
  onTest,
}: {
  k: KeyView;
  manage: boolean;
  weighted: boolean;
  probe?: LlmProbe;
  busy: boolean;
  onPatch: (v: { label?: string; weight?: number; disabled?: boolean }) => void;
  onDelete: () => void;
  onTest: () => void;
}) {
  const rest = cooldownText(k.cooldown_seconds);
  return (
    <li className="space-y-1 rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-slate-100 text-[11px] font-bold text-slate-600">
          {k.position}
        </span>
        <span className="font-medium text-slate-800">{k.label}</span>
        <code className="text-xs text-slate-500">{k.masked}</code>
        {k.disabled && <Badge tone="gray">꺼 둠</Badge>}
        {rest && <Badge tone="amber">쉬는 중 {rest}</Badge>}
        <span className="text-xs text-slate-500">
          호출 {k.calls}번{k.errors > 0 && ` · 실패 ${k.errors}번`}
        </span>
        <span className="ml-auto flex items-center gap-1">
          {weighted && (
            <label className="flex items-center gap-1 text-xs text-slate-500">
              비중
              <Select
                aria-label={`${k.label} 비중`}
                className="h-8 w-16 text-xs"
                value={k.weight}
                disabled={!manage}
                onChange={(e) => onPatch({ weight: Number(e.target.value) })}
              >
                {WEIGHTS.map((w) => (
                  <option key={w} value={w}>
                    {w}
                  </option>
                ))}
              </Select>
            </label>
          )}
          <Button size="sm" variant="ghost" disabled={busy} onClick={onTest}>
            <PlugZap className="h-3.5 w-3.5" /> {busy ? "확인 중…" : "연결 테스트"}
          </Button>
          {manage && !k.primary && (
            <>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`${k.label} ${k.disabled ? "켜기" : "끄기"}`}
                onClick={() => onPatch({ disabled: !k.disabled })}
              >
                {k.disabled ? "켜기" : "끄기"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="text-red-600"
                aria-label={`${k.label} 지우기`}
                onClick={() => {
                  if (window.confirm(`'${k.label}' 키를 지울까요?`)) onDelete();
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </>
          )}
        </span>
      </div>
      {k.last_error && <p className="text-xs text-red-600">마지막 오류: {k.last_error}</p>}
      {probe && (
        <p className={probe.ok ? "text-xs text-emerald-700" : "text-xs text-red-600"}>
          {probe.ok ? "✓ " : "✕ "}
          {probe.message} {probe.hint}
        </p>
      )}
    </li>
  );
}

export function LlmKeysPanel({
  ws,
  provider,
  manage,
}: {
  ws: string;
  provider: LlmProvider;
  manage: boolean;
}) {
  const p = asProviderV9(provider);
  const keys = p.keys ?? [];
  const strategy = p.key_strategy ?? "failover";
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ label: "", api_key: "", weight: 1 });
  const [probes, setProbes] = useState<Record<string, LlmProbe>>({});
  const add = useAddLlmKey(ws, p.id);
  const patch = usePatchLlmKey(ws, p.id);
  const del = useDeleteLlmKey(ws, p.id);
  const setStrategy = usePatchLlmProvider(ws, p.id);
  const test = useTestLlmKey(ws, p.id);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate(form, {
      onSuccess: () => {
        toast.success("키를 더했어요. 키는 암호화되어 다시 볼 수 없어요.");
        setForm({ label: "", api_key: "", weight: 1 });
      },
    });
  };

  return (
    <div className="basis-full">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-xs font-medium text-indigo-600 hover:text-indigo-500"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <KeyRound className="h-3.5 w-3.5" /> 키 {keys.length}개
        {keys.length > 1 && ` · ${strategyLabel(strategy)}`}
        <span className="font-normal text-slate-400">
          {open ? "접기" : "여러 개 두고 나눠 쓰기"}
        </span>
      </button>
      {open && (
        <div className="mt-2 space-y-3 rounded-lg bg-slate-50 p-3">
          {keys.length > 1 && (
            <label className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
              <span className="font-medium">돌려쓰기 방식</span>
              <Select
                aria-label="돌려쓰기 방식"
                className="h-8 w-44 text-xs"
                value={strategy}
                disabled={!manage || setStrategy.isPending}
                onChange={(e) =>
                  setStrategy.mutate(
                    { key_strategy: e.target.value },
                    { onError: (err) => toast.error(err) },
                  )
                }
              >
                {STRATEGIES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </Select>
              <span className="text-slate-400">
                {STRATEGIES.find((s) => s.value === strategy)?.hint}
              </span>
            </label>
          )}
          <ul className="space-y-2">
            {keys.map((k) => (
              <KeyRow
                key={k.id}
                k={k}
                manage={manage}
                weighted={strategy === "weighted"}
                probe={probes[k.id]}
                busy={test.isPending && test.variables === k.id}
                onPatch={(v) =>
                  k.primary && v.weight !== undefined
                    ? setStrategy.mutate({ primary_weight: v.weight })
                    : patch.mutate({ id: k.id, ...v }, { onError: (err) => toast.error(err) })
                }
                onDelete={() =>
                  del.mutate(k.id, {
                    onSuccess: () => toast.success("키를 지웠어요."),
                    onError: (err) => toast.error(err),
                  })
                }
                onTest={() =>
                  test.mutate(k.id, {
                    onSuccess: (r) => setProbes((m) => ({ ...m, [k.id]: r })),
                    onError: (err) => toast.error(err),
                  })
                }
              />
            ))}
          </ul>
          {manage && (
            <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
              <label className="space-y-0.5 text-xs text-slate-600">
                <span className="font-medium">이름(선택)</span>
                <Input
                  aria-label="새 키 이름"
                  className="h-9 w-32"
                  placeholder="예: 팀 B 키"
                  maxLength={60}
                  value={form.label}
                  onChange={(e) => setForm({ ...form, label: e.target.value })}
                />
              </label>
              <label className="space-y-0.5 text-xs text-slate-600">
                <span className="font-medium">API 키</span>
                <Input
                  aria-label="새 키 값"
                  className="h-9 w-56"
                  type="password"
                  autoComplete="off"
                  required
                  value={form.api_key}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                />
              </label>
              <label className="space-y-0.5 text-xs text-slate-600">
                <span className="font-medium">비중</span>
                <Select
                  aria-label="새 키 비중"
                  className="h-9 w-16"
                  value={form.weight}
                  onChange={(e) => setForm({ ...form, weight: Number(e.target.value) })}
                >
                  {WEIGHTS.map((w) => (
                    <option key={w} value={w}>
                      {w}
                    </option>
                  ))}
                </Select>
              </label>
              <Button
                type="submit"
                size="sm"
                disabled={add.isPending || form.api_key.trim().length < 4}
              >
                <Plus className="h-3.5 w-3.5" /> 키 더하기
              </Button>
            </form>
          )}
          <ErrorBox error={add.error ?? patch.error ?? del.error ?? setStrategy.error} />
          <p className="text-xs text-slate-500">
            한도(429)에 걸린 키는 1분, 키 오류가 난 키는 '연결 테스트'가 성공할 때까지 쉬고 다음
            키로 넘어가요. 기본 키는 끄거나 지울 수 없어요.
          </p>
        </div>
      )}
    </div>
  );
}
