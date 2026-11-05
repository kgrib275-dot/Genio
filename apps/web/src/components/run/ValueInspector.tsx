// 값 확인창: 실행에서 단계마다 나온 값을 '이름 = 값' 목록으로 보고, 검색하고, 값 끌어오기 경로를 복사한다.
import { ChevronDown, ChevronRight, Copy, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "@/components/ui/toast-store";
import { copyText, cn } from "@/lib/cn";
import { flattenValue, matchesQuery, refPath, type FlatValue } from "@/lib/valueFlatten";

export interface InspectorStep {
  nodeId: string;
  label: string;
  status: string;
  output: Record<string, unknown> | null;
}

const LONG = 120;

/** 값 몇 줄. 긴 값은 줄여 보이고 '더 보기'로 펼친다. 줄마다 값 끌어오기 경로를 복사할 수 있다. */
export function ValueRows({
  nodeId,
  rows,
  copyLabel = "값 끌어오기 경로 복사",
}: {
  nodeId: string;
  rows: FlatValue[];
  copyLabel?: string;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  if (rows.length === 0)
    return <p className="px-3 py-2 text-xs text-slate-500">보여 줄 값이 없어요.</p>;
  return (
    <ul className="divide-y divide-slate-100">
      {rows.map((r) => {
        const long = r.text.length > LONG && !open[r.path];
        const path = refPath(nodeId, r.path);
        return (
          <li key={r.path} className="flex items-start gap-2 px-3 py-1.5 text-xs">
            <code className="w-32 shrink-0 break-all text-slate-500 sm:w-40" title={path}>
              {r.path}
            </code>
            <div className="min-w-0 flex-1">
              <span
                className={cn(
                  "whitespace-pre-wrap break-words",
                  r.kind === "empty" ? "text-slate-400" : "text-slate-900",
                )}
              >
                {long ? `${r.text.slice(0, LONG)}…` : r.text}
              </span>
              {r.text.length > LONG && (
                <button
                  type="button"
                  className="ml-1 text-indigo-600 hover:underline"
                  onClick={() => setOpen((o) => ({ ...o, [r.path]: !o[r.path] }))}
                >
                  {open[r.path] ? "접기" : "더 보기"}
                </button>
              )}
            </div>
            <button
              type="button"
              title={`${copyLabel}: ${path}`}
              aria-label={`${r.path} ${copyLabel}`}
              className="shrink-0 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-indigo-700"
              onClick={async () => {
                if (await copyText(path))
                  toast.success(`${path} 복사했어요. 값 칸에 붙여 넣으세요.`);
              }}
            >
              <Copy className="h-3.5 w-3.5" />
            </button>
          </li>
        );
      })}
    </ul>
  );
}

const STATUS: Record<string, string> = {
  succeeded: "성공",
  failed: "실패",
  skipped: "건너뜀",
  running: "실행 중",
  waiting_approval: "승인 대기",
};

export function ValueInspector({
  steps,
  focusNodeId,
}: {
  steps: InspectorStep[];
  /** 캔버스에서 고른 단계(처음부터 펼친다) */
  focusNodeId?: string | null;
}) {
  const [query, setQuery] = useState("");
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  const groups = useMemo(
    () =>
      steps
        .filter((s) => s.output && Object.keys(s.output).length > 0)
        .map((s) => ({
          step: s,
          rows: flattenValue(s.output).filter((r) => matchesQuery(r, query)),
        })),
    [steps, query],
  );
  const searching = query.trim() !== "";
  const visible = groups.filter((g) => !searching || g.rows.length > 0);

  if (groups.length === 0) {
    return (
      <p className="px-3 py-3 text-xs text-slate-500">
        아직 확인할 값이 없어요. 실행하면 여기에 단계별 값이 나와요.
      </p>
    );
  }
  return (
    <div className="text-xs" data-testid="value-inspector">
      <div className="relative border-b border-slate-100 px-3 py-2">
        <Search className="pointer-events-none absolute left-5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
        <input
          type="search"
          aria-label="값 찾기"
          placeholder="값 이름이나 내용으로 찾기"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="h-8 w-full rounded-lg border border-slate-300 bg-white pl-8 pr-2 text-xs focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/15"
        />
      </div>
      {visible.length === 0 && (
        <p className="px-3 py-3 text-slate-500">찾는 값이 없어요. 다른 말로 찾아 보세요.</p>
      )}
      {visible.map(({ step, rows }) => {
        const defaultOpen = searching || step.nodeId === focusNodeId || groups.length <= 3;
        const isOpen = toggled[step.nodeId] ?? defaultOpen;
        return (
          <section key={step.nodeId} className="border-b border-slate-100 last:border-0">
            <button
              type="button"
              aria-expanded={isOpen}
              onClick={() => setToggled((t) => ({ ...t, [step.nodeId]: !isOpen }))}
              className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left hover:bg-slate-50"
            >
              {isOpen ? (
                <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5 text-slate-400" />
              )}
              <span className="font-medium text-slate-800">{step.label}</span>
              <span className="text-slate-400">
                ({step.nodeId}) · {STATUS[step.status] ?? step.status} · 값 {rows.length}개
              </span>
            </button>
            {isOpen && <ValueRows nodeId={step.nodeId} rows={rows} />}
          </section>
        );
      })}
    </div>
  );
}
