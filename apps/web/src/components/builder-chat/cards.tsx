import { useState } from "react";
import { Link } from "react-router-dom";
import { TOOL_LABEL } from "@/components/builder-chat/turn";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ko } from "@/i18n/ko";
import type { AskUser, MarketSuggestion, TestResult, ToolCallRecord } from "@/lib/api/types";

export function ToolCallCard({ call }: { call: ToolCallRecord }) {
  const [open, setOpen] = useState(false);
  const pending = call.ok === undefined;
  return (
    <div className="rounded border border-slate-200 bg-slate-50 text-xs">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-2 py-1 text-left"
      >
        <span aria-hidden>{pending ? "⏳" : call.ok ? "✔️" : "⚠️"}</span>
        <span className="font-medium text-slate-700">{TOOL_LABEL[call.name] ?? call.name}</span>
        {call.summary && <span className="truncate text-slate-500">{call.summary}</span>}
        <span className="ml-auto shrink-0 text-slate-400">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all border-t border-slate-200 px-2 py-1 text-[11px] text-slate-600">
          {JSON.stringify(call.input ?? {}, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function AskUserCard({
  ask,
  active,
  onPick,
}: {
  ask: AskUser;
  active: boolean;
  onPick: (option: string) => void;
}) {
  return (
    <div className="rounded-md border border-indigo-200 bg-indigo-50 px-3 py-2">
      <p className="text-sm text-indigo-900">{ask.question}</p>
      {ask.options.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {ask.options.map((o) => (
            <Button
              key={o}
              size="sm"
              variant="outline"
              disabled={!active}
              onClick={() => onPick(o)}
            >
              {o}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

export function MarketSuggestionCard({
  suggestion,
  active,
  canInstall,
  installing,
  onInstall,
}: {
  suggestion: MarketSuggestion;
  active: boolean;
  canInstall: boolean;
  installing: boolean;
  onInstall: () => void;
}) {
  const { item, reason } = suggestion;
  return (
    <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2">
      <p className="text-xs font-medium text-emerald-700">
        마켓 추천 · {ko.marketTypes[item.type] ?? item.type}
      </p>
      <p className="mt-0.5 text-sm font-semibold text-slate-900">{item.name}</p>
      <p className="text-xs text-slate-600">{item.summary}</p>
      {reason && <p className="mt-1 text-xs text-slate-500">추천 이유: {reason}</p>}
      <div className="mt-2 flex items-center gap-2">
        {item.installed ? (
          <span className="text-xs text-emerald-700">이미 설치되어 있어요.</span>
        ) : canInstall ? (
          <Button size="sm" disabled={!active || installing} onClick={onInstall}>
            {installing
              ? "설치 중…"
              : item.price > 0
                ? `설치하기 (${item.price}원, 모의 결제)`
                : "설치하기"}
          </Button>
        ) : (
          <span className="text-xs text-slate-500">
            설치는 관리자만 할 수 있어요. 관리자에게 요청해 주세요.
          </span>
        )}
        <Link to={`/market/${item.key}`} className="text-xs text-indigo-600 hover:underline">
          자세히
        </Link>
      </div>
    </div>
  );
}

export function TestResultCard({ result }: { result: TestResult }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-slate-500">테스트 실행</span>
        <StatusBadge status={result.status} />
        <Link
          to={`/runs/${result.run_id}`}
          className="ml-auto text-xs text-indigo-600 hover:underline"
        >
          상세
        </Link>
      </div>
      {result.output?.text && (
        <p className="mt-1 whitespace-pre-wrap text-slate-800">{result.output.text}</p>
      )}
      {result.error && <p className="mt-1 text-xs text-red-700">{result.error}</p>}
    </div>
  );
}
