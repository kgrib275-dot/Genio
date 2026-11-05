// 외부 추적 서비스 한 개의 설정 카드: 켜기, 입력 칸(서비스마다 다름), 표본·실패만, 상태, 연결 시험
import { Plus, PlugZap, Trash2, X } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import type { TraceKind, TraceProvider, TraceTestResult } from "@/lib/api/trace";
import { formatDate } from "@/lib/cn";
import {
  clampRate,
  isDirty,
  lastText,
  MAX_HEADERS,
  missingFields,
  type ProviderDraft,
} from "@/lib/tracingForm";

const TONE_TEXT = {
  green: "text-emerald-700",
  red: "text-red-600",
  gray: "text-slate-500",
} as const;

export function ProviderCard({
  draft,
  kind,
  saved,
  testing,
  onChange,
  onRemove,
  onTest,
}: {
  draft: ProviderDraft;
  kind: TraceKind;
  /** 서버에 저장돼 있는 모습(없으면 아직 저장 전) */
  saved: TraceProvider | undefined;
  testing: boolean;
  onChange: (next: ProviderDraft) => void;
  onRemove: () => void;
  onTest: () => Promise<TraceTestResult>;
}) {
  const [result, setResult] = useState<TraceTestResult | null>(null);
  const missing = missingFields(draft, kind, saved);
  const dirty = isDirty(draft, saved);
  const last = lastText(saved?.last, formatDate);
  const set = (patch: Partial<ProviderDraft>) => onChange({ ...draft, ...patch });
  const uid = draft.uid;

  return (
    <Card data-testid={`trace-${draft.kind}`}>
      <CardBody className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-base font-semibold text-slate-900">{kind.label}</span>
          {kind.experimental && (
            <span title="일부 요청 형식을 공식 문서로 확인하지 못했어요. 연결 시험으로 꼭 확인하세요.">
              <Badge tone="amber">실험적</Badge>
            </span>
          )}
          <Badge tone={draft.enabled ? "green" : "gray"}>{draft.enabled ? "켜짐" : "꺼짐"}</Badge>
          {missing.length > 0 && <Badge tone="red">설정 필요: {missing.join("·")}</Badge>}
          {!saved && <Badge tone="blue">저장 전</Badge>}
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto text-red-600"
            aria-label={`${draft.name} 지우기`}
            onClick={onRemove}
          >
            <Trash2 className="h-3.5 w-3.5" /> 지우기
          </Button>
        </div>
        <p className="-mt-2 text-xs text-slate-500">{kind.description}</p>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="이름(목록에서 구분용)" htmlFor={`name-${uid}`}>
            <Input
              id={`name-${uid}`}
              maxLength={60}
              value={draft.name}
              onChange={(e) => set({ name: e.target.value })}
            />
          </Field>
          <label
            htmlFor={`on-${uid}`}
            className="flex cursor-pointer items-center gap-2 self-end pb-2 text-sm"
          >
            <input
              id={`on-${uid}`}
              type="checkbox"
              className="h-4 w-4 accent-indigo-600"
              checked={draft.enabled}
              onChange={(e) => set({ enabled: e.target.checked })}
            />
            {kind.label}로 보내기
          </label>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {kind.fields.map((f) => {
            const id = `${f.key}-${uid}`;
            if (f.type === "secret") {
              const stored = saved?.secrets[f.key];
              const hint = stored?.has
                ? `저장됨 ${stored.masked}. 바꿀 때만 새로 넣으세요.`
                : f.hint || "암호화해서 저장하고 다시 보여 주지 않아요.";
              return (
                <Field
                  key={f.key}
                  label={f.required ? `${f.label} *` : f.label}
                  htmlFor={id}
                  hint={hint}
                >
                  <Input
                    id={id}
                    type="password"
                    autoComplete="off"
                    value={draft.secrets[f.key] ?? ""}
                    onChange={(e) =>
                      set({ secrets: { ...draft.secrets, [f.key]: e.target.value } })
                    }
                  />
                </Field>
              );
            }
            if (f.type === "headers") {
              return (
                <div key={f.key} className="space-y-2 sm:col-span-2">
                  <p className="text-sm font-medium text-slate-700">{f.label}</p>
                  {f.hint && <p className="text-xs text-slate-500">{f.hint}</p>}
                  {draft.headers.map((h, i) => (
                    <div key={i} className="flex flex-wrap items-center gap-2">
                      <Input
                        aria-label={`헤더 이름 ${i + 1}`}
                        className="w-44"
                        placeholder="Authorization"
                        value={h.name}
                        onChange={(e) =>
                          set({
                            headers: draft.headers.map((x, j) =>
                              j === i ? { ...x, name: e.target.value } : x,
                            ),
                          })
                        }
                      />
                      <Input
                        aria-label={`헤더 값 ${i + 1}`}
                        type="password"
                        autoComplete="off"
                        className="min-w-0 flex-1"
                        placeholder={h.masked ? `저장됨 ${h.masked}` : "값"}
                        value={h.value}
                        onChange={(e) =>
                          set({
                            headers: draft.headers.map((x, j) =>
                              j === i ? { ...x, value: e.target.value } : x,
                            ),
                          })
                        }
                      />
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`헤더 ${i + 1} 지우기`}
                        onClick={() => set({ headers: draft.headers.filter((_, j) => j !== i) })}
                      >
                        <X className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ))}
                  {draft.headers.length < MAX_HEADERS && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        set({ headers: [...draft.headers, { name: "", value: "", masked: "" }] })
                      }
                    >
                      <Plus className="h-3.5 w-3.5" /> 헤더 추가
                    </Button>
                  )}
                </div>
              );
            }
            return (
              <Field
                key={f.key}
                label={f.required ? `${f.label} *` : f.label}
                htmlFor={id}
                hint={f.hint || undefined}
              >
                <Input
                  id={id}
                  placeholder={f.placeholder || f.default}
                  value={draft.fields[f.key] ?? ""}
                  onChange={(e) => set({ fields: { ...draft.fields, [f.key]: e.target.value } })}
                />
              </Field>
            );
          })}
        </div>

        <div className="grid gap-3 rounded-lg bg-slate-50 p-3 sm:grid-cols-2">
          <Field
            label={`표본 비율 ${clampRate(draft.sample_rate)}%`}
            htmlFor={`rate-${uid}`}
            hint="100%면 모든 실행을 보내요. 줄이면 같은 비율만 골라 보내요(비용·양 줄이기)."
          >
            <input
              id={`rate-${uid}`}
              type="range"
              min={0}
              max={100}
              step={5}
              className="w-full accent-indigo-600"
              value={clampRate(draft.sample_rate)}
              onChange={(e) => set({ sample_rate: Number(e.target.value) })}
            />
          </Field>
          <label
            htmlFor={`fail-${uid}`}
            className="flex cursor-pointer items-start gap-2 self-center text-sm"
          >
            <input
              id={`fail-${uid}`}
              type="checkbox"
              className="mt-0.5 h-4 w-4 accent-indigo-600"
              checked={draft.only_failed}
              onChange={(e) => set({ only_failed: e.target.checked })}
            />
            <span>
              실패한 실행만 보내기
              <span className="block text-xs text-slate-500">성공한 실행은 보내지 않아요.</span>
            </span>
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={testing || !saved || missing.length > 0}
            onClick={async () => setResult(await onTest())}
          >
            <PlugZap className="h-4 w-4" /> 연결 시험
          </Button>
          {!saved ? (
            <span className="text-xs text-slate-500">먼저 저장하면 시험할 수 있어요.</span>
          ) : dirty ? (
            <span className="text-xs text-amber-700">
              시험은 저장된 설정으로 해요. 바꾼 값이 있으면 먼저 저장하세요.
            </span>
          ) : null}
          {result && (
            <span className={result.ok ? "text-xs text-emerald-700" : "text-xs text-red-600"}>
              {result.message}
            </span>
          )}
        </div>
        <p className={`text-xs ${TONE_TEXT[last.tone]}`} data-testid={`trace-last-${draft.kind}`}>
          {last.text}
        </p>
      </CardBody>
    </Card>
  );
}
