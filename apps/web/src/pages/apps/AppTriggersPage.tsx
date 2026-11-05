// 자동 실행(n8n Webhook·Schedule): 바깥 서비스가 부르는 주소, 정해진 시간에 실행.
import {
  CalendarClock,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  Webhook,
  X,
  Zap,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, Empty } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { useApp, useVersions } from "@/lib/api/apps";
import type { Trigger, TriggerKind } from "@/lib/api/types";
import {
  useCreateTrigger,
  useDeleteTrigger,
  useRotateTriggerToken,
  useRunTriggerNow,
  useTriggers,
  useUpdateTrigger,
  type NewTrigger,
} from "@/lib/api/v4";
import { cn, timeAgo } from "@/lib/cn";
import {
  cronFromForm,
  cronProblem,
  DEFAULT_SCHEDULE,
  describeCron,
  formFromCron,
  WEEKDAYS,
  type ScheduleForm,
  type SchedulePreset,
} from "@/lib/cron";
import { useListControls } from "@/lib/useListControls";
import { DataView } from "@/components/DataView";
import { useRotateTriggerSecret, useTriggerPayloads, type TriggerWithSecret } from "@/lib/api/v5b";
import { CopyBox, SecretOnce, Toggle } from "@/components/triggers/parts";
import { serviceConfigOf, useServicePresets } from "@/lib/api/v9events";
import { AppNav } from "@/pages/apps/AppNav";
import { ServiceTriggerDialog, ServiceTriggerItem } from "@/pages/apps/ServiceTriggers";
import { canEdit, canViewRuns, useSession } from "@/store/session";

const TIMEZONES = [
  { value: "Asia/Seoul", label: "한국 시간(서울)" },
  { value: "Asia/Tokyo", label: "일본 시간(도쿄)" },
  { value: "UTC", label: "세계 표준시(UTC)" },
  { value: "America/New_York", label: "미국 동부(뉴욕)" },
  { value: "America/Los_Angeles", label: "미국 서부(LA)" },
  { value: "Europe/London", label: "영국(런던)" },
];

const PRESETS: { value: SchedulePreset; label: string }[] = [
  { value: "hourly", label: "매시간" },
  { value: "daily", label: "매일" },
  { value: "weekdays", label: "평일(월~금)" },
  { value: "weekly", label: "매주" },
  { value: "custom", label: "직접 입력(cron)" },
];

interface Row {
  key: string;
  value: string;
}

function rowsFrom(input: Record<string, unknown> | undefined): Row[] {
  return Object.entries(input ?? {}).map(([key, v]) => ({
    key,
    value: typeof v === "string" ? v : JSON.stringify(v),
  }));
}

/** 칸에 적은 글을 값으로: 숫자·참/거짓·JSON처럼 보이면 그 형태로, 아니면 글 그대로 */
function parseValue(v: string): unknown {
  const t = v.trim();
  if (t === "true" || t === "false") return t === "true";
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t);
  if (/^[[{]/.test(t)) {
    try {
      return JSON.parse(t) as unknown;
    } catch {
      return v;
    }
  }
  return v;
}

function inputFrom(rows: Row[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const r of rows) if (r.key.trim()) out[r.key.trim()] = parseValue(r.value);
  return out;
}

function when(iso: string | null): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("ko-KR", {
    month: "long",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function curlExample(url: string, fields: string[]): string {
  const body = Object.fromEntries((fields.length ? fields : ["message"]).map((k) => [k, "값"]));
  return `curl -X POST '${url}' \\\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify(body)}'`;
}

function signedCurlExample(url: string, fields: string[]): string {
  const body = JSON.stringify(
    Object.fromEntries((fields.length ? fields : ["message"]).map((k) => [k, "값"])),
  );
  return [
    "# 1) 보낼 내용과 지금 시각(초)",
    `BODY='${body}'`,
    "TS=$(date +%s)",
    "# 2) 서명 = HMAC-SHA256(비밀값, 시각.내용)",
    'SIG=$(printf "%s.%s" "$TS" "$BODY" | openssl dgst -sha256 -hmac "$GENIO_SECRET" | sed "s/^.* //")',
    `curl -X POST '${url}' \\`,
    "  -H 'Content-Type: application/json' \\",
    '  -H "X-Genio-Timestamp: $TS" \\',
    '  -H "X-Genio-Signature: sha256=$SIG" \\',
    '  -d "$BODY"',
  ].join("\n");
}

/** 서명 비밀값: 이번 한 번만 보여 준다 */
/** 최근 받은 값(최대 5개). 인증·서명 헤더는 저장하지 않아요. */
function Payloads({ triggerId }: { triggerId: string }) {
  const q = useTriggerPayloads(triggerId);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const list = q.data ?? [];
  if (list.length === 0)
    return (
      <p className="text-xs text-slate-500">아직 받은 값이 없어요. 위 예시로 한 번 보내 보세요.</p>
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
            {p.note && <span className="text-red-700">{p.note}</span>}
            {p.run_id && (
              <Link to={`/runs/${p.run_id}`} className="text-indigo-600 hover:underline">
                실행 보기
              </Link>
            )}
            {p.truncated && <span className="text-slate-400">(4KB까지만 저장)</span>}
          </div>
          <DataView value={p.body} />
        </li>
      ))}
    </ul>
  );
}

// ---------------- 만들기·고치기 ----------------
function TriggerDialog({
  appId,
  kind,
  editing,
  inputKeys,
  onClose,
}: {
  appId: string;
  kind: TriggerKind;
  editing: Trigger | null;
  inputKeys: string[];
  onClose: () => void;
}) {
  const create = useCreateTrigger(appId);
  const update = useUpdateTrigger(appId);
  const versions = useVersions(appId);
  const cfg = editing?.config ?? {};
  const [name, setName] = useState(editing?.name ?? "");
  const [mode, setMode] = useState<"async" | "sync">(cfg.mode ?? "async");
  const [signed, setSigned] = useState<boolean>(
    Boolean((cfg as { require_signature?: boolean }).require_signature),
  );
  const [secret, setSecret] = useState<string | null>(null);
  const [version, setVersion] = useState<string>(cfg.version ? String(cfg.version) : "");
  const [sched, setSched] = useState<ScheduleForm>(
    cfg.cron ? formFromCron(cfg.cron) : DEFAULT_SCHEDULE,
  );
  const [tz, setTz] = useState(cfg.timezone ?? "Asia/Seoul");
  const [rows, setRows] = useState<Row[]>(
    editing ? rowsFrom(cfg.input) : inputKeys.map((key) => ({ key, value: "" })),
  );
  const cron = cronFromForm(sched);
  const problem = kind === "schedule" ? cronProblem(cron) : null;
  const pending = create.isPending || update.isPending;
  const error = create.error ?? update.error;

  const submit = () => {
    const ver = version ? Number(version) : null;
    const config: NewTrigger["config"] =
      kind === "webhook"
        ? ({ mode, version: ver, require_signature: signed } as NewTrigger["config"])
        : { cron, timezone: tz, input: inputFrom(rows), version: ver };
    const done = (t: Trigger) => {
      toast.success(editing ? "자동 실행을 고쳤어요." : "자동 실행을 만들었어요.");
      const sec = (t as TriggerWithSecret).secret;
      if (sec) setSecret(sec);
      else onClose();
    };
    if (editing) update.mutate({ id: editing.id, name, config }, { onSuccess: done });
    else create.mutate({ kind, name, enabled: true, config }, { onSuccess: done });
  };

  return (
    <Dialog
      open
      wide
      onClose={onClose}
      title={
        editing
          ? "자동 실행 고치기"
          : kind === "webhook"
            ? "외부에서 받기 만들기"
            : "예약 만들기(정해진 시간에)"
      }
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            취소
          </Button>
          <Button onClick={submit} disabled={pending || Boolean(problem)}>
            {pending ? "저장 중…" : editing ? "저장" : "만들기"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="이름(내가 알아보기 위한 것)" htmlFor="tr-name">
          <Input
            id="tr-name"
            value={name}
            placeholder={kind === "webhook" ? "예: 쇼핑몰 주문 알림" : "예: 매일 아침 보고서"}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>

        {secret && <SecretOnce secret={secret} onDone={onClose} />}
        {kind === "webhook" && (
          <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-slate-200 px-3 py-2">
            <input
              type="checkbox"
              checked={signed}
              onChange={(e) => setSigned(e.target.checked)}
              className="mt-0.5 accent-indigo-600"
            />
            <span>
              <span className="block text-sm font-medium text-slate-800">서명 확인 켜기(추천)</span>
              <span className="block text-xs text-slate-500">
                보내는 쪽이 비밀값으로 만든 서명(X-Genio-Signature)이 맞을 때만 받아요. 주소가 새어
                나가도 남이 흐름을 실행할 수 없어요.
              </span>
            </span>
          </label>
        )}
        {kind === "webhook" ? (
          <fieldset className="space-y-1.5">
            <legend className="mb-1 text-xs font-medium text-slate-600">응답 방식</legend>
            {(
              [
                [
                  "async",
                  "바로 받기",
                  "요청을 받자마자 실행 번호만 돌려줘요. 오래 걸리는 흐름에 알맞아요.",
                ],
                [
                  "sync",
                  "결과 기다리기",
                  "최대 30초 기다려 흐름의 결과를 돌려줘요. 답을 바로 써야 할 때.",
                ],
              ] as const
            ).map(([v, label, desc]) => (
              <label
                key={v}
                className={cn(
                  "flex cursor-pointer gap-2 rounded-lg border px-3 py-2",
                  mode === v ? "border-indigo-400 bg-indigo-50" : "border-slate-200",
                )}
              >
                <input
                  type="radio"
                  name="tr-mode"
                  checked={mode === v}
                  onChange={() => setMode(v)}
                  className="mt-0.5 accent-indigo-600"
                />
                <span>
                  <span className="block text-sm font-medium text-slate-800">{label}</span>
                  <span className="block text-xs text-slate-500">{desc}</span>
                </span>
              </label>
            ))}
          </fieldset>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="언제" htmlFor="tr-preset">
                <Select
                  id="tr-preset"
                  value={sched.preset}
                  onChange={(e) =>
                    setSched({
                      ...sched,
                      preset: e.target.value as SchedulePreset,
                      custom: sched.preset === "custom" ? sched.custom : cronFromForm(sched),
                    })
                  }
                >
                  {PRESETS.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </Select>
              </Field>
              {sched.preset === "weekly" && (
                <Field label="요일" htmlFor="tr-dow">
                  <Select
                    id="tr-dow"
                    value={sched.weekday}
                    onChange={(e) => setSched({ ...sched, weekday: Number(e.target.value) })}
                  >
                    {WEEKDAYS.map((d, i) => (
                      <option key={d} value={i}>
                        {d}요일
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
              {sched.preset === "hourly" && (
                <Field label="몇 분에" htmlFor="tr-min">
                  <Input
                    id="tr-min"
                    type="number"
                    min={0}
                    max={59}
                    value={sched.minute}
                    onChange={(e) => setSched({ ...sched, minute: Number(e.target.value) })}
                  />
                </Field>
              )}
              {(sched.preset === "daily" ||
                sched.preset === "weekdays" ||
                sched.preset === "weekly") && (
                <Field label="시각" htmlFor="tr-time">
                  <Input
                    id="tr-time"
                    type="time"
                    value={`${String(sched.hour).padStart(2, "0")}:${String(sched.minute).padStart(2, "0")}`}
                    onChange={(e) => {
                      const [h, m] = e.target.value.split(":").map(Number);
                      setSched({ ...sched, hour: h ?? 0, minute: m ?? 0 });
                    }}
                  />
                </Field>
              )}
              {sched.preset === "custom" && (
                <Field label="cron 식(분 시 일 월 요일)" htmlFor="tr-cron">
                  <Input
                    id="tr-cron"
                    className="font-mono"
                    value={sched.custom}
                    placeholder="*/30 9-18 * * 1-5"
                    onChange={(e) => setSched({ ...sched, custom: e.target.value })}
                  />
                </Field>
              )}
              <Field label="시간대" htmlFor="tr-tz">
                <Select id="tr-tz" value={tz} onChange={(e) => setTz(e.target.value)}>
                  {TIMEZONES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <p className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">
              <CalendarClock className="mr-1 inline h-4 w-4 text-indigo-500" />
              {problem ? (
                <span className="text-red-700">일정 형식이 맞지 않아요. {problem}</span>
              ) : (
                <>
                  {describeCron(cron)}에 실행해요{" "}
                  <code className="ml-1 text-xs text-slate-400">{cron}</code>
                </>
              )}
            </p>
            <div>
              <p className="mb-1 text-xs font-medium text-slate-600">실행할 때 넣을 입력</p>
              <div className="space-y-1.5">
                {rows.map((r, i) => (
                  <div key={i} className="flex gap-1.5">
                    <Input
                      aria-label="입력 이름"
                      className="w-1/3"
                      placeholder="이름(예: message)"
                      value={r.key}
                      onChange={(e) =>
                        setRows(rows.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))
                      }
                    />
                    <Input
                      aria-label="입력 값"
                      className="flex-1"
                      placeholder="값"
                      value={r.value}
                      onChange={(e) =>
                        setRows(rows.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))
                      }
                    />
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label="이 입력 빼기"
                      onClick={() => setRows(rows.filter((_, j) => j !== i))}
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setRows([...rows, { key: "", value: "" }])}
                >
                  <Plus className="h-3.5 w-3.5" /> 입력 추가
                </Button>
              </div>
              <p className="mt-1 text-[11px] text-slate-400">
                숫자·true/false는 그 값으로, 나머지는 글로 넣어요. 템플릿으로 오늘 날짜 같은 값이
                필요하면 흐름 안에서 날짜·시간 단계를 쓰세요.
              </p>
            </div>
          </>
        )}

        <Field label="실행할 버전" htmlFor="tr-ver">
          <Select id="tr-ver" value={version} onChange={(e) => setVersion(e.target.value)}>
            <option value="">가장 최근에 저장한 버전</option>
            {(versions.data ?? []).map((v) => (
              <option key={v.id} value={v.version}>
                버전 {v.version}
                {v.note ? ` · ${v.note}` : ""}
              </option>
            ))}
          </Select>
        </Field>
        {versions.data && versions.data.length === 0 && (
          <p className="text-xs text-amber-700">
            아직 저장한 버전이 없어요. 자동 실행은 저장한 버전으로만 돌아요. 만들기 화면에서 버전
            저장을 먼저 하세요.
          </p>
        )}
        <ErrorBox error={error} />
      </div>
    </Dialog>
  );
}

// ---------------- 한 줄 ----------------
function TriggerItem({
  t,
  appId,
  editable,
  inputKeys,
  onEdit,
}: {
  t: Trigger;
  appId: string;
  editable: boolean;
  inputKeys: string[];
  onEdit: () => void;
}) {
  const update = useUpdateTrigger(appId);
  const rotate = useRotateTriggerToken(appId);
  const runNow = useRunTriggerNow(appId);
  const del = useDeleteTrigger(appId);
  const [showCurl, setShowCurl] = useState(false);
  const [showPayloads, setShowPayloads] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const rotateSecret = useRotateTriggerSecret(appId);
  const signed = Boolean((t.config as { require_signature?: boolean }).require_signature);
  const isHook = t.kind === "webhook";
  const Icon = isHook ? Webhook : CalendarClock;
  const input = (t.config.input ?? {}) as Record<string, unknown>;

  return (
    <li className={cn("space-y-2 px-4 py-4 sm:px-5", !t.enabled && "bg-slate-50/60")}>
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
            isHook ? "bg-violet-50 text-violet-600" : "bg-sky-50 text-sky-600",
          )}
        >
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-slate-900">
            {t.name || (isHook ? "외부에서 받기" : "예약")}
          </p>
          <p className="text-xs text-slate-500">
            {isHook
              ? t.config.mode === "sync"
                ? "외부에서 받기 · 결과 기다리기"
                : "외부에서 받기 · 바로 받기"
              : `${describeCron(t.config.cron ?? "")} · ${TIMEZONES.find((z) => z.value === t.config.timezone)?.label ?? t.config.timezone ?? ""}`}
            {t.config.version ? ` · 버전 ${t.config.version}` : " · 최근 버전"}
          </p>
        </div>
        <Badge tone={t.enabled ? "green" : "gray"}>{t.enabled ? "켜짐" : "꺼짐"}</Badge>
        <Toggle
          label={`${t.name || "자동 실행"} ${t.enabled ? "끄기" : "켜기"}`}
          checked={t.enabled}
          disabled={!editable || update.isPending}
          onChange={(v) =>
            update.mutate({ id: t.id, enabled: v }, { onError: (err) => toast.error(err) })
          }
        />
      </div>

      {isHook && t.url && (
        <div className="space-y-1.5">
          <CopyBox text={t.url} label="주소" />
          <div className="flex flex-wrap gap-1.5">
            <Button size="sm" variant="ghost" onClick={() => setShowCurl((v) => !v)}>
              {showCurl ? "예시 접기" : "부르는 예시(cURL) 보기"}
            </Button>
            {editable && (
              <Button
                size="sm"
                variant="ghost"
                disabled={rotate.isPending}
                onClick={() => {
                  if (
                    window.confirm(
                      "주소를 새로 만들까요? 지금 주소는 바로 쓸 수 없게 돼요. 바깥 서비스에 새 주소를 다시 넣어야 해요.",
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
            )}
          </div>
          {showCurl && (
            <CopyBox
              text={signed ? signedCurlExample(t.url, inputKeys) : curlExample(t.url, inputKeys)}
              label="예시"
            />
          )}
          <div className="flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs">
            <span className="font-medium text-slate-700">서명 확인</span>
            <Toggle
              label={signed ? "서명 확인 끄기" : "서명 확인 켜기"}
              checked={signed}
              disabled={!editable || update.isPending}
              onChange={(v) =>
                update.mutate(
                  { id: t.id, config: { require_signature: v } as NewTrigger["config"] },
                  {
                    onSuccess: (res) => {
                      const sec = (res as TriggerWithSecret).secret;
                      if (sec) setSecret(sec);
                    },
                    onError: (err) => toast.error(err),
                  },
                )
              }
            />
            <span className="text-slate-500">
              {signed ? "서명이 맞는 요청만 받아요." : "주소만 알면 누구나 보낼 수 있어요."}
            </span>
            {editable && signed && (
              <Button
                size="sm"
                variant="ghost"
                disabled={rotateSecret.isPending}
                onClick={() => {
                  if (
                    window.confirm(
                      "비밀값을 새로 만들까요? 예전 비밀값으로 만든 서명은 바로 거절돼요.",
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
          </div>
          {secret && <SecretOnce secret={secret} onDone={() => setSecret(null)} />}
          {editable && (
            <Button size="sm" variant="ghost" onClick={() => setShowPayloads((v) => !v)}>
              {showPayloads ? "받은 값 접기" : "최근 받은 값 보기"}
            </Button>
          )}
          {showPayloads && <Payloads triggerId={t.id} />}
          <p className="text-[11px] text-slate-400">
            이 주소를 아는 누구나 흐름을 실행할 수 있어요. 비밀번호처럼 다루세요.
          </p>
        </div>
      )}

      {!isHook && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
          <span>
            다음 실행:{" "}
            <b className="font-medium text-slate-700">
              {t.enabled ? when(t.next_run_at) : "꺼져 있어요"}
            </b>
          </span>
          {Object.keys(input).length > 0 && (
            <span className="flex flex-wrap gap-1">
              {Object.entries(input).map(([k, v]) => (
                <span key={k} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px]">
                  <span className="text-slate-500">{k}</span>{" "}
                  <span className="font-medium text-slate-700">
                    {typeof v === "string" ? v : JSON.stringify(v)}
                  </span>
                </span>
              ))}
            </span>
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
              disabled={runNow.isPending}
              onClick={() =>
                runNow.mutate(t.id, {
                  onSuccess: (r) =>
                    toast.success(
                      `지금 실행했어요. 실행 기록에서 결과를 보세요. (${r.id.slice(0, 8)})`,
                    ),
                  onError: (err) => toast.error(err),
                })
              }
            >
              <Play className="h-3.5 w-3.5" /> 지금 실행
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
                if (window.confirm(`'${t.name || "자동 실행"}'을(를) 지울까요?`))
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

const KIND_LABEL: Record<TriggerKind, string> = {
  webhook: "외부에서 받기",
  schedule: "예약",
  service: "서비스 이벤트",
};

export default function AppTriggersPage() {
  const { id: appId = "" } = useParams();
  const role = useSession((s) => s.role);
  const app = useApp(appId);
  const triggers = useTriggers(appId, canViewRuns(role));
  const editable = canEdit(role);
  const presets = useServicePresets(appId, editable);
  const [dialog, setDialog] = useState<{ kind: TriggerKind; editing: Trigger | null } | null>(null);

  // 흐름의 입력 칸 이름(예시·예약 입력에 미리 채움)
  const inputKeys = useMemo(() => {
    const nodes = (app.data?.draft_graph?.nodes ?? []) as {
      type: string;
      data?: { fields?: { key?: string }[] };
    }[];
    const input = nodes.find((n) => n.type === "input");
    return (input?.data?.fields ?? []).map((f) => f.key ?? "").filter(Boolean);
  }, [app.data]);

  const c = useListControls(triggers.data, {
    key: "triggers",
    defaultSize: 10,
    search: (t) =>
      `${t.name} ${KIND_LABEL[t.kind]} ${t.config.cron ? describeCron(t.config.cron) : ""}`,
    filters: [
      {
        id: "kind",
        label: "종류",
        options: [
          { value: "webhook", label: "외부에서 받기" },
          { value: "service", label: "서비스 이벤트" },
          { value: "schedule", label: "예약" },
        ],
        match: (t, v) => t.kind === v,
      },
      {
        id: "state",
        label: "상태",
        options: [
          { value: "on", label: "켜짐" },
          { value: "off", label: "꺼짐" },
        ],
        match: (t, v) => (v === "on") === t.enabled,
      },
    ],
  });

  return (
    <div className="flex min-h-full flex-col">
      <AppNav appId={appId} title={app.data?.name ?? ""} icon={app.data?.icon} help="triggers" />
      <div className="mx-auto w-full max-w-4xl space-y-5 px-4 py-6 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-slate-900">자동 실행</h2>
            <p className="text-sm text-slate-500">
              바깥 서비스가 주소로 부르거나(외부에서 받기), Slack·GitHub 같은 서비스에 일이 생기면
              (서비스 이벤트), 정해진 시간마다(예약) 이 흐름을 실행해요.
            </p>
          </div>
          {editable && (
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                onClick={() => setDialog({ kind: "service", editing: null })}
              >
                <Zap className="h-4 w-4" /> 서비스 이벤트로 시작
              </Button>
              <Button
                variant="outline"
                onClick={() => setDialog({ kind: "webhook", editing: null })}
              >
                <Webhook className="h-4 w-4" /> 외부에서 받기 만들기
              </Button>
              <Button onClick={() => setDialog({ kind: "schedule", editing: null })}>
                <CalendarClock className="h-4 w-4" /> 예약 만들기
              </Button>
            </div>
          )}
        </div>

        {(app.isLoading || triggers.isLoading) && <Loading />}
        <ErrorBox error={app.error ?? triggers.error} />

        {triggers.data && triggers.data.length === 0 && (
          <Empty icon={<CalendarClock className="h-10 w-10" />}>
            <p className="font-medium text-slate-700">아직 자동 실행이 없어요</p>
            <p className="max-w-md">
              <b>외부에서 받기</b>는 쇼핑몰·설문·다른 자동화 도구가 주소로 부르면 흐름을 실행해요.{" "}
              <b>서비스 이벤트</b>는 Slack 메시지·GitHub 이슈·Shopify 주문 같은 일이 생기면
              시작해요. <b>예약</b>은 &quot;평일 아침 9시&quot;처럼 정한 시간에 실행해요.
            </p>
          </Empty>
        )}

        {triggers.data && triggers.data.length > 0 && (
          <div className="space-y-3">
            <ListToolbar c={c} placeholder="이름·일정 검색" />
            <Card className="overflow-hidden">
              <ul className="divide-y divide-slate-100">
                {c.pageItems.map((t) =>
                  t.kind === "service" ? (
                    <ServiceTriggerItem
                      key={t.id}
                      t={t}
                      appId={appId}
                      editable={editable}
                      preset={presets.data?.find((p) => p.key === serviceConfigOf(t).service)}
                      onEdit={() => setDialog({ kind: t.kind, editing: t })}
                    />
                  ) : (
                    <TriggerItem
                      key={t.id}
                      t={t}
                      appId={appId}
                      editable={editable}
                      inputKeys={inputKeys}
                      onEdit={() => setDialog({ kind: t.kind, editing: t })}
                    />
                  ),
                )}
              </ul>
              <NoMatch c={c} />
            </Card>
            <ListPager c={c} />
          </div>
        )}
      </div>
      {dialog && dialog.kind === "service" && (
        <ServiceTriggerDialog
          key={dialog.editing?.id ?? "service-new"}
          appId={appId}
          editing={dialog.editing}
          presets={presets.data ?? []}
          inputKeys={inputKeys}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog && dialog.kind !== "service" && (
        <TriggerDialog
          key={dialog.editing?.id ?? dialog.kind}
          appId={appId}
          kind={dialog.kind}
          editing={dialog.editing}
          inputKeys={inputKeys}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}
