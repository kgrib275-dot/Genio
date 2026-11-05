// 서비스 이벤트로 시작하기(v0.9): Slack·GitHub·Shopify·Telegram·Jira·Typeform의 알림을 받아 흐름을 실행한다.
import {
  ChevronDown,
  ChevronUp,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { DataView } from "@/components/DataView";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { CopyBox, SecretOnce, Toggle } from "@/components/triggers/parts";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import type { Trigger } from "@/lib/api/types";
import { useDeleteTrigger, useRotateTriggerToken } from "@/lib/api/v4";
import { useRotateTriggerSecret, useTriggerPayloads, type TriggerWithSecret } from "@/lib/api/v5b";
import {
  serviceConfigOf,
  useCreateServiceTrigger,
  useSetProviderSecret,
  useTestSample,
  useUpdateServiceTrigger,
  type ServicePreset,
} from "@/lib/api/v9events";
import { cn, timeAgo } from "@/lib/cn";
import { filterPaths, flattenPaths, type PathItem } from "@/lib/payloadPaths";

interface Row {
  key: string;
  path: string;
}

function rowsFrom(mapping: Record<string, string>): Row[] {
  return Object.entries(mapping).map(([key, path]) => ({ key, path }));
}

function mappingFrom(rows: Row[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of rows) {
    const key = r.key.trim();
    const path = r.path.trim();
    if (key && path) out[key] = path;
  }
  return out;
}

/** 받은 값에서 위치를 골라 '값 연결' 칸에 넣는 목록 */
function PathPicker({ items, onPick }: { items: PathItem[]; onPick: (path: string) => void }) {
  const [q, setQ] = useState("");
  const shown = filterPaths(items, q).slice(0, 60);
  return (
    <div className="space-y-1.5 rounded-lg border border-slate-200 bg-slate-50 p-2">
      <Input
        aria-label="받은 값 찾기"
        placeholder="받은 값 찾기(예: title)"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        className="h-8 text-xs"
      />
      {shown.length === 0 ? (
        <p className="px-1 py-2 text-xs text-slate-500">맞는 값이 없어요.</p>
      ) : (
        <ul className="max-h-44 space-y-0.5 overflow-y-auto">
          {shown.map((i) => (
            <li key={i.path}>
              <button
                type="button"
                onClick={() => onPick(i.path)}
                className="flex w-full items-baseline gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-indigo-50"
              >
                <code className="shrink-0 font-mono text-[11px] text-indigo-700">{i.path}</code>
                <span className="min-w-0 flex-1 truncate text-slate-500">{i.sample}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------- 만들기·고치기 ----------------
export function ServiceTriggerDialog({
  appId,
  editing,
  presets,
  inputKeys,
  onClose,
}: {
  appId: string;
  editing: Trigger | null;
  presets: ServicePreset[];
  inputKeys: string[];
  onClose: () => void;
}) {
  const create = useCreateServiceTrigger(appId);
  const update = useUpdateServiceTrigger(appId);
  const cfg = editing ? serviceConfigOf(editing) : null;
  const [serviceKey, setServiceKey] = useState(cfg?.service ?? "");
  const [name, setName] = useState(editing?.name ?? "");
  const [events, setEvents] = useState<string[]>(cfg?.events ?? []);
  const [includeBot, setIncludeBot] = useState(cfg?.include_bot ?? false);
  const [rows, setRows] = useState<Row[]>(rowsFrom(cfg?.mapping ?? {}));
  const [secretIn, setSecretIn] = useState("");
  const [picking, setPicking] = useState<number | null>(null);
  const [created, setCreated] = useState<TriggerWithSecret | null>(null);

  const preset = presets.find((p) => p.key === serviceKey) ?? null;
  const received = useTriggerPayloads(editing?.id ?? "", Boolean(editing));
  // 값을 고를 수 있는 위치: 실제로 받은 값(있으면)과 서비스의 샘플
  const items = useMemo(() => {
    const real = (received.data ?? []).find(
      (p) => p.accepted && p.body && typeof p.body === "object",
    );
    const merged = [
      ...flattenPaths(real?.body ?? null, 80),
      ...flattenPaths(preset?.sample.body, 80),
    ];
    const seen = new Set<string>();
    return merged.filter((i) => (seen.has(i.path) ? false : (seen.add(i.path), true)));
  }, [received.data, preset]);

  const needsSecret = !editing && preset?.key_origin === "provider";
  const secretProblem = needsSecret && secretIn.trim().length < 8;
  const pending = create.isPending || update.isPending;
  const error = create.error ?? update.error;

  const save = () => {
    if (!preset) return;
    const config = {
      service: preset.key,
      events,
      mapping: mappingFrom(rows),
      include_bot: includeBot,
    };
    if (editing) {
      update.mutate(
        { id: editing.id, name: name.trim() || undefined, config },
        {
          onSuccess: () => {
            toast.success("저장했어요.");
            onClose();
          },
        },
      );
      return;
    }
    create.mutate(
      {
        name: name.trim() || undefined,
        config,
        secret: preset.key_origin === "provider" ? secretIn.trim() : undefined,
      },
      { onSuccess: (t) => setCreated(t) },
    );
  };

  // 만든 직후: 주소·비밀값·연결 방법을 한 번 보여 준다
  if (created && preset) {
    return (
      <Dialog
        open
        onClose={onClose}
        title={`${preset.name} 이벤트를 만들었어요`}
        footer={<Button onClick={onClose}>다 했어요</Button>}
      >
        <div className="space-y-3 text-sm">
          {created.url && (
            <div className="space-y-1">
              <p className="text-xs font-medium text-slate-600">받는 주소</p>
              <CopyBox text={created.url} label="주소" />
            </div>
          )}
          {created.secret ? (
            <div className="space-y-1">
              <p className="text-xs font-medium text-slate-600">{preset.key_label}</p>
              <SecretOnce secret={created.secret} />
            </div>
          ) : (
            <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
              {preset.name}에서 받은 {preset.key_label}로 알림이 진짜인지 확인해요.
            </p>
          )}
          <div>
            <p className="mb-1 text-xs font-medium text-slate-600">{preset.name}에 연결하는 방법</p>
            <ol className="list-decimal space-y-1 pl-5 text-xs leading-relaxed text-slate-700 marker:text-indigo-500">
              {preset.instructions.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
          </div>
        </div>
      </Dialog>
    );
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={editing ? "서비스 이벤트 고치기" : "서비스 이벤트로 시작"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            닫기
          </Button>
          <Button disabled={!preset || pending || Boolean(secretProblem)} onClick={save}>
            {pending ? "저장하는 중…" : editing ? "저장" : "만들기"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {!preset && (
          <div className="space-y-2">
            <p className="text-sm text-slate-600">어느 서비스의 알림으로 이 흐름을 시작할까요?</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {presets.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  onClick={() => {
                    setServiceKey(p.key);
                    setName(`${p.name} 이벤트`);
                  }}
                  className="rounded-xl border border-slate-200 px-3 py-3 text-left hover:border-indigo-300 hover:bg-indigo-50/40"
                >
                  <p className="text-sm font-semibold text-slate-900">{p.name}</p>
                  <p className="mt-0.5 text-[11px] text-slate-500">
                    {p.events
                      .slice(0, 2)
                      .map((e) => e.label)
                      .join(" · ")}
                    {p.events.length > 2 ? " …" : ""}
                  </p>
                </button>
              ))}
            </div>
          </div>
        )}

        {preset && (
          <>
            <Field label="이름" htmlFor="svc-name">
              <Input
                id="svc-name"
                value={name}
                maxLength={100}
                placeholder={`${preset.name} 이벤트`}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>

            {!editing && (
              <div className="rounded-lg bg-slate-50 px-3 py-2.5 text-xs text-slate-600">
                <p className="mb-1 font-medium text-slate-700">{preset.name}에 연결하는 방법</p>
                <ol className="list-decimal space-y-0.5 pl-4 leading-relaxed">
                  {preset.instructions.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ol>
              </div>
            )}

            {needsSecret && (
              <Field
                label={preset.key_label}
                htmlFor="svc-secret"
                hint="이 값으로 받은 알림이 진짜인지 확인해요. 저장하면 다시 볼 수 없어요."
              >
                <Input
                  id="svc-secret"
                  type="password"
                  autoComplete="off"
                  value={secretIn}
                  onChange={(e) => setSecretIn(e.target.value)}
                />
              </Field>
            )}

            <div>
              <p className="mb-1.5 text-xs font-medium text-slate-700">
                어떤 일이 생기면 시작할까요?{" "}
                <span className="font-normal text-slate-400">(하나도 안 고르면 모두)</span>
              </p>
              <div className="flex flex-wrap gap-1.5">
                {preset.events.map((e) => {
                  const on = events.includes(e.id);
                  return (
                    <button
                      key={e.id}
                      type="button"
                      aria-pressed={on}
                      onClick={() =>
                        setEvents((cur) => (on ? cur.filter((x) => x !== e.id) : [...cur, e.id]))
                      }
                      className={cn(
                        "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                        on
                          ? "border-indigo-600 bg-indigo-600 text-white"
                          : "border-slate-200 bg-white text-slate-600 hover:border-slate-300",
                      )}
                    >
                      {e.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {preset.key === "slack" && (
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={includeBot}
                  onChange={(e) => setIncludeBot(e.target.checked)}
                  className="accent-indigo-600"
                />
                봇이 보낸 메시지도 받기
              </label>
            )}

            <div className="space-y-2">
              <div>
                <p className="text-xs font-medium text-slate-700">받은 값을 입력 칸에 넣기</p>
                <p className="text-[11px] text-slate-500">
                  비워 두면 <b>message</b> 칸에 한 줄 요약이 들어가요. 더 넣고 싶은 값은 &quot;받은
                  값에서 고르기&quot;로 골라요.
                </p>
              </div>
              {rows.map((r, i) => (
                <div key={i} className="space-y-1.5">
                  <div className="flex items-center gap-1.5">
                    <Input
                      aria-label="입력 칸 이름"
                      list="svc-input-keys"
                      placeholder="입력 칸 이름"
                      value={r.key}
                      className="h-9 w-32 shrink-0"
                      onChange={(e) =>
                        setRows((cur) =>
                          cur.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)),
                        )
                      }
                    />
                    <Input
                      aria-label="받은 값 위치"
                      placeholder="받은 값 위치(예: issue.title)"
                      value={r.path}
                      className="h-9 min-w-0 flex-1 font-mono text-xs"
                      onChange={(e) =>
                        setRows((cur) =>
                          cur.map((x, j) => (j === i ? { ...x, path: e.target.value } : x)),
                        )
                      }
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setPicking(picking === i ? null : i)}
                    >
                      고르기
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label="이 줄 지우기"
                      onClick={() => {
                        setRows((cur) => cur.filter((_, j) => j !== i));
                        setPicking(null);
                      }}
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                  {picking === i && (
                    <PathPicker
                      items={items}
                      onPick={(path) => {
                        setRows((cur) => cur.map((x, j) => (j === i ? { ...x, path } : x)));
                        setPicking(null);
                      }}
                    />
                  )}
                </div>
              ))}
              <datalist id="svc-input-keys">
                {inputKeys.map((k) => (
                  <option key={k} value={k} />
                ))}
              </datalist>
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  setRows((cur) => [...cur, { key: inputKeys[cur.length] ?? "", path: "" }])
                }
              >
                <Plus className="h-3.5 w-3.5" /> 값 하나 더 넣기
              </Button>
            </div>
            <ErrorBox error={error} />
          </>
        )}
      </div>
    </Dialog>
  );
}

// ---------------- 목록의 한 줄 ----------------
function ReceivedList({ triggerId }: { triggerId: string }) {
  const q = useTriggerPayloads(triggerId);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const list = q.data ?? [];
  if (list.length === 0)
    return (
      <p className="text-xs text-slate-500">
        아직 받은 알림이 없어요. &quot;샘플로 시험&quot;을 누르거나 서비스에서 이벤트를 만들어
        보세요.
      </p>
    );
  return (
    <ul className="space-y-2">
      {list.map((p, i) => (
        <li key={`${p.received_at}-${i}`} className="rounded-lg border border-slate-200 p-2">
          <div className="mb-1 flex flex-wrap items-center gap-2 text-xs">
            <Badge tone={p.accepted ? "green" : "red"}>{p.accepted ? "받음" : "거절"}</Badge>
            <span className="text-slate-500">
              {new Date(p.received_at).toLocaleString("ko-KR")}
            </span>
            {p.note && <span className="text-slate-600">{p.note}</span>}
            {p.run_id && (
              <Link to={`/runs/${p.run_id}`} className="text-indigo-600 hover:underline">
                실행 보기
              </Link>
            )}
          </div>
          <DataView value={p.body} />
        </li>
      ))}
    </ul>
  );
}

export function ServiceTriggerItem({
  t,
  appId,
  editable,
  preset,
  onEdit,
}: {
  t: Trigger;
  appId: string;
  editable: boolean;
  preset: ServicePreset | undefined;
  onEdit: () => void;
}) {
  const cfg = serviceConfigOf(t);
  const update = useUpdateServiceTrigger(appId);
  const rotate = useRotateTriggerToken(appId);
  const rotateSecret = useRotateTriggerSecret(appId);
  const setProvider = useSetProviderSecret(appId);
  const sample = useTestSample(appId);
  const del = useDeleteTrigger(appId);
  const [secret, setSecret] = useState<string | null>(null);
  const [showHow, setShowHow] = useState(false);
  const [showReceived, setShowReceived] = useState(false);
  const [newProviderSecret, setNewProviderSecret] = useState<string | null>(null);
  const [sampleInput, setSampleInput] = useState<Record<string, unknown> | null>(null);
  const provider = preset?.key_origin === "provider";
  const eventLabels = cfg.events.map((id) => preset?.events.find((e) => e.id === id)?.label ?? id);
  const mapped = Object.keys(cfg.mapping).length;

  return (
    <li className={cn("space-y-2 px-4 py-4 sm:px-5", !t.enabled && "bg-slate-50/60")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-600">
          <Zap className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-slate-900">
            {t.name || `${preset?.name ?? cfg.service} 이벤트`}
          </p>
          <p className="text-xs text-slate-500">
            서비스 이벤트 · {preset?.name ?? cfg.service} ·{" "}
            {eventLabels.length ? eventLabels.join(", ") : "모든 이벤트"}
            {mapped > 0 ? ` · 값 ${mapped}개 연결` : ""}
          </p>
        </div>
        <Badge tone={t.enabled ? "green" : "gray"}>{t.enabled ? "켜짐" : "꺼짐"}</Badge>
        <Toggle
          label={`${t.name || "서비스 이벤트"} ${t.enabled ? "끄기" : "켜기"}`}
          checked={t.enabled}
          disabled={!editable || update.isPending}
          onChange={(v) =>
            update.mutate({ id: t.id, enabled: v }, { onError: (err) => toast.error(err) })
          }
        />
      </div>

      {t.url && (
        <div className="space-y-1.5">
          <CopyBox text={t.url} label="주소" />
          <div className="flex flex-wrap gap-1.5">
            {preset && (
              <Button size="sm" variant="ghost" onClick={() => setShowHow((v) => !v)}>
                {showHow ? (
                  <ChevronUp className="h-3.5 w-3.5" />
                ) : (
                  <ChevronDown className="h-3.5 w-3.5" />
                )}{" "}
                {preset.name}에 연결하는 방법
              </Button>
            )}
            {editable && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={rotate.isPending}
                  onClick={() => {
                    if (
                      window.confirm(
                        "주소를 새로 만들까요? 지금 주소는 바로 쓸 수 없게 돼요. 서비스에 새 주소를 다시 넣어야 해요.",
                      )
                    )
                      rotate.mutate(t.id, {
                        onSuccess: () => toast.success("새 주소를 만들었어요."),
                        onError: (err) => toast.error(err),
                      });
                  }}
                >
                  <RefreshCw className="h-3.5 w-3.5" /> 주소 새로 만들기
                </Button>
                {!provider && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={rotateSecret.isPending}
                    onClick={() => {
                      if (
                        window.confirm(
                          "비밀값을 새로 만들까요? 예전 비밀값으로 보낸 알림은 바로 거절돼요. 서비스에도 새 비밀값을 넣어야 해요.",
                        )
                      )
                        rotateSecret.mutate(t.id, {
                          onSuccess: (res) => setSecret(res.secret ?? null),
                          onError: (err) => toast.error(err),
                        });
                    }}
                  >
                    <RefreshCw className="h-3.5 w-3.5" /> 비밀값 새로 만들기
                  </Button>
                )}
              </>
            )}
          </div>
          {showHow && preset && (
            <ol className="list-decimal space-y-1 rounded-lg bg-slate-50 py-2 pl-7 pr-3 text-xs leading-relaxed text-slate-700">
              {preset.instructions.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
          )}
          {secret && <SecretOnce secret={secret} onDone={() => setSecret(null)} />}
          {editable && provider && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs">
              <span className="font-medium text-slate-700">{preset?.key_label}</span>
              {newProviderSecret === null ? (
                <Button size="sm" variant="ghost" onClick={() => setNewProviderSecret("")}>
                  바꾸기
                </Button>
              ) : (
                <>
                  <Input
                    aria-label="새 비밀값"
                    type="password"
                    autoComplete="off"
                    value={newProviderSecret}
                    className="h-8 w-56 text-xs"
                    onChange={(e) => setNewProviderSecret(e.target.value)}
                  />
                  <Button
                    size="sm"
                    disabled={newProviderSecret.trim().length < 8 || setProvider.isPending}
                    onClick={() =>
                      setProvider.mutate(
                        { id: t.id, secret: newProviderSecret.trim() },
                        {
                          onSuccess: () => {
                            toast.success("비밀값을 바꿨어요.");
                            setNewProviderSecret(null);
                          },
                          onError: (err) => toast.error(err),
                        },
                      )
                    }
                  >
                    저장
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setNewProviderSecret(null)}>
                    취소
                  </Button>
                </>
              )}
            </div>
          )}
          {editable && (
            <Button size="sm" variant="ghost" onClick={() => setShowReceived((v) => !v)}>
              {showReceived ? "받은 값 접기" : "받은 값 미리 보기(최근 5개)"}
            </Button>
          )}
          {showReceived && <ReceivedList triggerId={t.id} />}
          {sampleInput && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
              <p className="mb-1 font-medium">샘플로 이렇게 입력이 채워져 실행됐어요</p>
              <ul className="space-y-0.5">
                {Object.entries(sampleInput).map(([k, v]) => (
                  <li key={k} className="flex gap-2">
                    <span className="w-24 shrink-0 text-emerald-700">{k}</span>
                    <span className="min-w-0 flex-1 break-words">
                      {typeof v === "string" ? v : JSON.stringify(v)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        {t.last_run_at ? (
          <span className="flex items-center gap-1.5">
            마지막 실행 {timeAgo(t.last_run_at)}
            {t.last_status && <StatusBadge status={t.last_status} />}
            {t.last_run_id && (
              <Link to={`/runs/${t.last_run_id}`} className="text-indigo-600 hover:underline">
                자세히
              </Link>
            )}
          </span>
        ) : (
          <span>아직 실행한 적 없어요</span>
        )}
        {editable && (
          <span className="ml-auto flex gap-1">
            <Button
              size="sm"
              variant="outline"
              disabled={sample.isPending}
              onClick={() =>
                sample.mutate(t.id, {
                  onSuccess: (r) => {
                    setSampleInput(r.input);
                    toast.success(
                      `샘플로 실행했어요. 실행 기록에서 결과를 보세요. (${r.run.id.slice(0, 8)})`,
                    );
                  },
                  onError: (err) => toast.error(err),
                })
              }
            >
              <Play className="h-3.5 w-3.5" /> 샘플로 시험
            </Button>
            <Button size="sm" variant="ghost" aria-label="고치기" title="고치기" onClick={onEdit}>
              <Pencil className="h-3.5 w-3.5" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-red-600"
              aria-label="지우기"
              title="지우기"
              disabled={del.isPending}
              onClick={() => {
                if (window.confirm(`'${t.name || "서비스 이벤트"}'을(를) 지울까요?`))
                  del.mutate(t.id, {
                    onSuccess: () => toast.success("지웠어요."),
                    onError: (err) => toast.error(err),
                  });
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </span>
        )}
      </div>
    </li>
  );
}
