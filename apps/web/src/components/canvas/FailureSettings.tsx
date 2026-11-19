import { ChevronDown, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Input, Select, Textarea } from "@/components/ui/input";
import { cn } from "@/lib/cn";

type OnError = "stop" | "default" | "branch";

interface Retry {
  max_retries?: number;
  interval_ms?: number;
}

const DEFAULT_TIMEOUT_TEXT = "60초";

/** 단계 공통 "실패했을 때" 설정(_retry, _on_error, _default, _timeout). 바뀐 data 전체를 onChange로 넘긴다. */
export function FailureSettings({
  data,
  onChange,
  readOnly,
}: {
  data: Record<string, unknown>;
  onChange: (data: Record<string, unknown>) => void;
  readOnly?: boolean;
}) {
  const retry = (data._retry as Retry | undefined) ?? {};
  const onError = (data._on_error as OnError | undefined) ?? "stop";
  const configured =
    Boolean(retry.max_retries) || onError !== "stop" || typeof data._timeout === "number";
  const [open, setOpen] = useState(configured);
  const [defaultText, setDefaultText] = useState(() =>
    JSON.stringify(data._default ?? {}, null, 2),
  );
  const [jsonError, setJsonError] = useState("");

  const set = (patch: Record<string, unknown>) => onChange({ ...data, ...patch });

  return (
    <div className="mt-4 rounded-xl border border-slate-200">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-semibold text-slate-700"
        aria-expanded={open}
      >
        <ShieldAlert className="h-3.5 w-3.5 text-slate-400" />
        실패했을 때
        {configured && (
          <span className="rounded-full bg-indigo-50 px-1.5 text-[10px] text-indigo-700">
            설정됨
          </span>
        )}
        <ChevronDown
          className={cn("ml-auto h-3.5 w-3.5 transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-100 px-3 py-3 text-xs">
          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1">
              <span className="block font-medium text-slate-600">다시 시도 횟수</span>
              <Input
                type="number"
                min={0}
                max={5}
                disabled={readOnly}
                aria-label="다시 시도 횟수"
                value={retry.max_retries ?? 0}
                onChange={(e) =>
                  set({
                    _retry: {
                      ...retry,
                      max_retries: Math.max(0, Math.min(5, Number(e.target.value) || 0)),
                    },
                  })
                }
              />
            </label>
            <label className="space-y-1">
              <span className="block font-medium text-slate-600">간격(밀리초)</span>
              <Input
                type="number"
                min={100}
                max={5000}
                step={100}
                disabled={readOnly}
                aria-label="다시 시도 간격"
                value={retry.interval_ms ?? 1000}
                onChange={(e) =>
                  set({
                    _retry: {
                      ...retry,
                      interval_ms: Math.max(100, Math.min(5000, Number(e.target.value) || 1000)),
                    },
                  })
                }
              />
            </label>
          </div>
          <label className="block space-y-1">
            <span className="block font-medium text-slate-600">
              제한 시간(초, 비우면 기본 {DEFAULT_TIMEOUT_TEXT})
            </span>
            <Input
              type="number"
              min={1}
              max={600}
              disabled={readOnly}
              aria-label="제한 시간"
              placeholder="기본"
              value={typeof data._timeout === "number" ? data._timeout : ""}
              onChange={(e) => {
                const v = e.target.value === "" ? undefined : Number(e.target.value);
                set({
                  _timeout:
                    v === undefined || Number.isNaN(v) ? undefined : Math.max(1, Math.min(600, v)),
                });
              }}
            />
          </label>
          <label className="block space-y-1">
            <span className="block font-medium text-slate-600">그래도 실패하면</span>
            <Select
              aria-label="실패 처리 방식"
              disabled={readOnly}
              value={onError}
              onChange={(e) => set({ _on_error: e.target.value as OnError })}
            >
              <option value="stop">흐름을 멈춰요</option>
              <option value="default">기본값으로 계속해요</option>
              <option value="branch">&apos;실패 시&apos; 출구로 보내요</option>
            </Select>
          </label>
          {onError === "default" && (
            <label className="block space-y-1">
              <span className="block font-medium text-slate-600">대신 쓸 결과(JSON 형식)</span>
              <Textarea
                aria-label="기본 출력"
                disabled={readOnly}
                className="font-mono text-xs"
                value={defaultText}
                onChange={(e) => {
                  setDefaultText(e.target.value);
                  try {
                    const parsed: unknown = JSON.parse(e.target.value || "{}");
                    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
                      setJsonError("");
                      set({ _default: parsed });
                    } else setJsonError("{ } 형태의 객체로 적어 주세요.");
                  } catch {
                    setJsonError("JSON 형식이 맞지 않아요. 쉼표와 따옴표를 확인하세요.");
                  }
                }}
              />
              {jsonError && <span className="text-red-600">{jsonError}</span>}
            </label>
          )}
          {onError === "branch" && (
            <p className="text-slate-500">
              단계 오른쪽에 &apos;실패 시&apos; 출구가 생겨요. 실패 내용은 &apos;값 끌어오기&apos;의
              오류 항목으로 쓸 수 있어요.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/** 값 고정 안내: 고정한 결과가 있으면 시험에서 이 단계를 건너뛰고 그 값을 쓴다. 해제하면 값을 지운다. */
export function PinSettings({
  data,
  onChange,
  readOnly,
}: {
  data: Record<string, unknown>;
  onChange: (data: Record<string, unknown>) => void;
  readOnly?: boolean;
}) {
  const pinned = data._pinned as { output?: Record<string, unknown> } | undefined;
  if (!pinned?.output) return null;
  const keys = Object.keys(pinned.output);
  return (
    <div
      className="mt-4 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-xs text-indigo-900"
      data-testid="pin-settings"
    >
      <p className="font-medium">고정한 값을 써요(시험 전용)</p>
      <p className="mt-0.5 text-indigo-800">
        시험 실행에서는 이 단계를 실행하지 않고 고정한 결과({keys.slice(0, 4).join(", ")}
        {keys.length > 4 ? " 외" : ""})를 넘겨요. 실서비스 실행에는 영향이 없어요.
      </p>
      {!readOnly && (
        <button
          type="button"
          className="mt-1.5 rounded-md border border-indigo-300 bg-white px-2 py-0.5 text-indigo-800 hover:bg-indigo-100"
          onClick={() => {
            const rest = { ...data };
            delete rest._pinned;
            onChange(rest);
          }}
        >
          고정 해제
        </button>
      )}
    </div>
  );
}
