// 실행 입력·출력, 활동 기록 세부 내용 같은 데이터를 JSON 대신 읽기 쉬운 목록으로 보여 준다.
// 개발자용으로 '원본 보기'를 누르면 JSON 원문도 볼 수 있다.
import { ChevronDown, ChevronRight, Code2, List } from "lucide-react";
import { useState, type ReactNode } from "react";
import { cn, copyText } from "@/lib/cn";
import { keyLabel } from "@/lib/dataLabels";
import { toast } from "@/components/ui/toast-store";

const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

function Primitive({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-slate-400">없음</span>;
  if (typeof value === "boolean")
    return (
      <span
        className={cn(
          "inline-flex rounded px-1.5 py-0.5 text-[11px] font-medium",
          value ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600",
        )}
      >
        {value ? "예" : "아니오"}
      </span>
    );
  if (typeof value === "number")
    return <span className="tabular-nums text-slate-900">{value.toLocaleString()}</span>;
  const s = String(value);
  if (s === "") return <span className="text-slate-400">(빈 값)</span>;
  if (ISO.test(s)) {
    const d = new Date(s);
    if (!Number.isNaN(d.getTime()))
      return <span className="text-slate-900">{d.toLocaleString("ko-KR")}</span>;
  }
  return <span className="whitespace-pre-wrap break-words text-slate-900">{s}</span>;
}

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

const MAX_ITEMS = 20;

function Node({ value, depth }: { value: unknown; depth: number }) {
  const [more, setMore] = useState(false);
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-slate-400">(비어 있음)</span>;
    const shown = more ? value : value.slice(0, MAX_ITEMS);
    const simple = value.every((v) => !isObj(v) && !Array.isArray(v));
    return (
      <div>
        {simple ? (
          <ul className="flex flex-wrap gap-1">
            {shown.map((v, i) => (
              <li key={i} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px]">
                <Primitive value={v} />
              </li>
            ))}
          </ul>
        ) : (
          <ol className="space-y-1.5">
            {shown.map((v, i) => (
              <li key={i} className="flex gap-2">
                <span className="mt-0.5 shrink-0 text-[10px] font-semibold text-slate-400">
                  {i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <Node value={v} depth={depth + 1} />
                </div>
              </li>
            ))}
          </ol>
        )}
        {value.length > MAX_ITEMS && (
          <button
            type="button"
            onClick={() => setMore((m) => !m)}
            className="mt-1 text-[11px] font-medium text-indigo-600 hover:underline"
          >
            {more ? "접기" : `${value.length - MAX_ITEMS}개 더 보기`}
          </button>
        )}
      </div>
    );
  }
  if (isObj(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) return <span className="text-slate-400">(비어 있음)</span>;
    return (
      <dl
        className={cn(
          "grid grid-cols-[minmax(72px,max-content)_1fr] gap-x-3 gap-y-1",
          depth > 0 && "border-l-2 border-slate-200 pl-2",
        )}
      >
        {entries.map(([k, v]) => (
          <Row key={k} k={k} v={v} depth={depth} />
        ))}
      </dl>
    );
  }
  return <Primitive value={value} />;
}

function Row({ k, v, depth }: { k: string; v: unknown; depth: number }) {
  const nested = (isObj(v) && Object.keys(v).length > 0) || (Array.isArray(v) && v.length > 0);
  const [open, setOpen] = useState(depth < 2);
  const label = keyLabel(k);
  return (
    <>
      <dt className="min-w-0 break-words pt-0.5 text-[11px] font-medium text-slate-500" title={k}>
        {nested ? (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="inline-flex items-center gap-0.5 hover:text-slate-800"
            aria-expanded={open}
          >
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {label}
          </button>
        ) : (
          label
        )}
      </dt>
      <dd className="min-w-0 text-xs">
        {nested && !open ? (
          <span className="text-[11px] text-slate-400">
            {Array.isArray(v) ? `${v.length}개 항목` : `${Object.keys(v as object).length}개 값`}
          </span>
        ) : (
          <Node value={v} depth={depth + 1} />
        )}
      </dd>
    </>
  );
}

/** 데이터를 목록으로 보여 준다. raw를 켜면 '원본 보기' 버튼이 생긴다. */
export function DataView({
  value,
  className,
  raw = true,
  empty,
}: {
  value: unknown;
  className?: string;
  raw?: boolean;
  empty?: ReactNode;
}) {
  const [showRaw, setShowRaw] = useState(false);
  if (value === null || value === undefined || (isObj(value) && Object.keys(value).length === 0))
    return <span className="text-xs text-slate-400">{empty ?? "-"}</span>;
  // 문자열이 JSON이면 풀어서 보여 준다
  let v = value;
  if (typeof value === "string" && /^\s*[[{]/.test(value)) {
    try {
      v = JSON.parse(value);
    } catch {
      v = value;
    }
  }
  const text = typeof v === "string" ? v : JSON.stringify(v, null, 2);
  return (
    <div
      className={cn(
        "relative max-h-80 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-2.5",
        className,
      )}
    >
      {raw && typeof v !== "string" && (
        <div className="sticky top-0 z-10 float-right ml-2 flex gap-0.5 rounded-md bg-slate-50/90">
          <button
            type="button"
            onClick={() => setShowRaw((s) => !s)}
            title={showRaw ? "목록으로 보기" : "원본 보기"}
            aria-label={showRaw ? "목록으로 보기" : "원본 보기"}
            className="rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
          >
            {showRaw ? <List className="h-3.5 w-3.5" /> : <Code2 className="h-3.5 w-3.5" />}
          </button>
        </div>
      )}
      {showRaw ? (
        <pre
          className="whitespace-pre-wrap break-all font-mono text-[11px] text-slate-700"
          onDoubleClick={async () => {
            if (await copyText(text)) toast.success("복사했어요.");
          }}
        >
          {text}
        </pre>
      ) : (
        <Node value={v} depth={0} />
      )}
    </div>
  );
}
