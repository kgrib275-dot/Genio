// '값 끌어오기'(기능 정의서 S2): 앞 단계 값을 골라 넣는 입력칸.
// 보통 모드에서는 {{n1.message}} 대신 «사용자 입력 › 메시지»로 보여 주고, 고급 모드에서만 {{ }}를 직접 쓴다.
import { Braces, ChevronDown, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  autocompleteAt,
  completeAt,
  filterOptions,
  flatOptions,
  insertAt,
  refsIn,
  removeRef,
  toDisplay,
  toRaw,
  valueGroups,
  type ValueGroup,
  type ValueOption,
} from "@/components/canvas/valueRefs";
import { useNodeTypes } from "@/lib/api/workspace";
import { cn } from "@/lib/cn";
import { useCanvas } from "@/store/canvas";

const ADV_KEY = "genio.values.advanced";

function readAdvanced(): boolean {
  try {
    return window.localStorage.getItem(ADV_KEY) === "1";
  } catch {
    return false;
  }
}

function writeAdvanced(v: boolean) {
  try {
    window.localStorage.setItem(ADV_KEY, v ? "1" : "0");
  } catch {
    // 기억하지 못해도 동작에는 문제없다
  }
}

/** 지금 고른 단계에서 끌어올 수 있는 값 묶음 */
function useValueGroups(wsId: string): ValueGroup[] {
  const graph = useCanvas((s) => s.graph);
  const current = useCanvas((s) => s.selectedId);
  const specs = useNodeTypes(wsId);
  return useMemo(
    () =>
      current
        ? valueGroups(
            graph.nodes.map((n) => ({
              id: n.id,
              type: n.type,
              data: (n.data ?? {}) as Record<string, unknown>,
            })),
            graph.edges,
            specs.data ?? [],
            current,
            (graph.variables ?? {}) as Record<string, unknown>,
          )
        : [],
    [graph, current, specs.data],
  );
}

type Field = HTMLInputElement | HTMLTextAreaElement;

const inputCls =
  "w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500";

/** 값 고르기 목록(단계별로 묶음) */
function Picker({
  groups,
  onPick,
  onClose,
}: {
  groups: ValueGroup[];
  onPick: (o: ValueOption) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const shown = q.trim()
    ? [{ id: "q", label: "찾은 값", items: filterOptions(flatOptions(groups), q.trim(), 30) }]
    : groups;
  return (
    <div
      role="dialog"
      aria-label="값 끌어오기"
      className="absolute left-0 right-0 top-full z-30 mt-1 max-h-72 overflow-y-auto rounded-lg border border-slate-200 bg-white p-2 shadow-lift"
      onKeyDown={(e) => e.key === "Escape" && onClose()}
    >
      {groups.length === 0 ? (
        <p className="px-1 py-2 text-xs text-slate-500">
          앞 단계와 선으로 이어야 그 단계의 값을 끌어올 수 있어요.
        </p>
      ) : (
        <>
          <input
            autoFocus
            aria-label="값 찾기"
            placeholder="값 이름으로 찾기"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="mb-2 w-full rounded-md border border-slate-200 px-2 py-1 text-xs focus:border-indigo-500 focus:outline-none"
          />
          {shown.map((g) => (
            <div key={g.id} className="mb-1.5">
              <p className="px-1 text-[11px] font-semibold text-slate-400">{g.label}</p>
              <ul>
                {g.items.map((o) => (
                  <li key={o.expr}>
                    <button
                      type="button"
                      onClick={() => onPick(o)}
                      className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-xs hover:bg-indigo-50"
                    >
                      <span className="min-w-0 flex-1 truncate text-slate-800">{o.item}</span>
                      <code className="shrink-0 text-[10px] text-slate-400">{o.expr}</code>
                    </button>
                  </li>
                ))}
                {g.items.length === 0 && (
                  <li className="px-1.5 py-1 text-xs text-slate-400">맞는 값이 없어요.</li>
                )}
              </ul>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

export function ValueInput({
  id,
  value,
  onChange,
  wsId,
  multiline = false,
  mono = false,
  disabled = false,
  placeholder,
}: {
  id: string;
  value: string | undefined;
  onChange: (v: string | undefined) => void;
  wsId: string;
  multiline?: boolean;
  mono?: boolean;
  disabled?: boolean;
  placeholder?: string;
}) {
  const groups = useValueGroups(wsId);
  const options = useMemo(() => flatOptions(groups), [groups]);
  const [advanced, setAdvancedState] = useState(readAdvanced);
  const [open, setOpen] = useState(false);
  const [suggest, setSuggest] = useState<{ start: number; query: string } | null>(null);
  const ref = useRef<Field | null>(null);
  const pendingCursor = useRef<number | null>(null);
  const raw = value ?? "";
  const shown = advanced ? raw : toDisplay(raw, options);
  const refs = refsIn(raw, options);

  useEffect(() => {
    const c = pendingCursor.current;
    if (c !== null && ref.current) {
      ref.current.focus();
      ref.current.setSelectionRange(c, c);
      pendingCursor.current = null;
    }
  });

  const setAdvanced = (v: boolean) => {
    setAdvancedState(v);
    writeAdvanced(v);
    setSuggest(null);
  };

  const emit = (nextShown: string) => {
    const nextRaw = advanced ? nextShown : toRaw(nextShown, options);
    onChange(nextRaw === "" ? undefined : nextRaw);
  };

  const pick = (o: ValueOption) => {
    const el = ref.current;
    const start = el?.selectionStart ?? shown.length;
    const end = el?.selectionEnd ?? shown.length;
    const token = advanced ? `{{${o.expr}}}` : `«${o.label}»`;
    const r = insertAt(shown, start, end, token);
    pendingCursor.current = r.cursor;
    emit(r.text);
    setOpen(false);
  };

  const onKeyDown = (e: KeyboardEvent<Field>) => {
    const el = e.currentTarget;
    // 보통 모드: 칩(«…») 바로 뒤에서 지우면 칩 전체를 지운다
    if (!advanced && e.key === "Backspace" && el.selectionStart === el.selectionEnd) {
      const pos = el.selectionStart ?? 0;
      if (shown[pos - 1] === "»") {
        const open = shown.lastIndexOf("«", pos - 1);
        if (open >= 0) {
          e.preventDefault();
          pendingCursor.current = open;
          emit(shown.slice(0, open) + shown.slice(pos));
        }
      }
    }
    if (advanced && suggest && e.key === "Escape") setSuggest(null);
  };

  const onInput = (text: string, cursor: number) => {
    emit(text);
    setSuggest(advanced ? autocompleteAt(text, cursor) : null);
  };

  const candidates = suggest ? filterOptions(options, suggest.query) : [];
  const common = {
    id,
    value: shown,
    disabled,
    placeholder,
    onKeyDown,
    className: cn(
      inputCls,
      mono || advanced ? "font-mono text-xs" : "",
      multiline && "min-h-[90px]",
    ),
  };

  return (
    <div className="relative">
      {multiline ? (
        <textarea
          {...common}
          ref={(el) => {
            ref.current = el;
          }}
          onChange={(e) =>
            onInput(e.target.value, e.target.selectionStart ?? e.target.value.length)
          }
        />
      ) : (
        <input
          {...common}
          ref={(el) => {
            ref.current = el;
          }}
          onChange={(e) =>
            onInput(e.target.value, e.target.selectionStart ?? e.target.value.length)
          }
        />
      )}
      {advanced && suggest && candidates.length > 0 && (
        <ul
          role="listbox"
          aria-label="값 자동완성"
          className="absolute left-0 right-0 top-full z-30 mt-1 max-h-48 overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 shadow-lift"
        >
          {candidates.map((o) => (
            <li key={o.expr}>
              <button
                type="button"
                className="flex w-full items-center gap-2 px-2 py-1 text-left text-xs hover:bg-indigo-50"
                onMouseDown={(e) => {
                  e.preventDefault();
                  const el = ref.current;
                  const cursor = el?.selectionStart ?? shown.length;
                  const r = completeAt(shown, suggest.start, cursor, o.expr);
                  pendingCursor.current = r.cursor;
                  emit(r.text);
                  setSuggest(null);
                }}
              >
                <code className="text-slate-700">{o.expr}</code>
                <span className="truncate text-slate-400">{o.label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {!disabled && (
        <div className="mt-1 flex flex-wrap items-center gap-1">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="inline-flex items-center gap-1 rounded-md border border-indigo-200 bg-indigo-50 px-1.5 py-0.5 text-[11px] font-medium text-indigo-700 hover:bg-indigo-100"
          >
            <Sparkles className="h-3 w-3" /> 값 끌어오기 <ChevronDown className="h-3 w-3" />
          </button>
          {!advanced &&
            refs.map((r) => (
              <span
                key={r.expr}
                className={cn(
                  "inline-flex max-w-full items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px]",
                  r.label ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800",
                )}
                title={
                  r.label ? `{{${r.expr}}}` : "앞 단계에 없는 값이에요. 고급 모드에서 확인하세요."
                }
              >
                <span className="truncate">{r.label ?? r.expr}</span>
                <button
                  type="button"
                  aria-label={`${r.label ?? r.expr} 빼기`}
                  className="rounded-full p-0.5 hover:bg-black/5"
                  onClick={() => {
                    const next = removeRef(raw, r.expr);
                    onChange(next === "" ? undefined : next);
                  }}
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </span>
            ))}
          <button
            type="button"
            onClick={() => setAdvanced(!advanced)}
            aria-pressed={advanced}
            title={advanced ? "읽기 쉬운 모양으로 보기" : "{{ }} 표현식을 직접 쓰기(고급)"}
            className={cn(
              "ml-auto inline-flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px]",
              advanced ? "bg-indigo-600 text-white" : "text-slate-400 hover:bg-slate-100",
            )}
          >
            <Braces className="h-3 w-3" /> 고급
          </button>
        </div>
      )}
      {open && <Picker groups={groups} onPick={pick} onClose={() => setOpen(false)} />}
    </div>
  );
}

/** JSON 칸용: 고른 값을 {{ }} 그대로 커서에 넣는 작은 버튼 */
export function RawValueButton({
  wsId,
  onInsert,
}: {
  wsId: string;
  onInsert: (token: string) => void;
}) {
  const groups = useValueGroups(wsId);
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 rounded-md border border-indigo-200 bg-indigo-50 px-1.5 py-0.5 text-[11px] font-medium text-indigo-700 hover:bg-indigo-100"
      >
        <Sparkles className="h-3 w-3" /> 값 끌어오기
      </button>
      {open && (
        <div className="absolute left-0 top-full z-30 w-64">
          <Picker
            groups={groups}
            onPick={(o) => {
              onInsert(`{{${o.expr}}}`);
              setOpen(false);
            }}
            onClose={() => setOpen(false)}
          />
        </div>
      )}
    </span>
  );
}
