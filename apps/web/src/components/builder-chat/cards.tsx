import { DataView } from "@/components/DataView";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ExternalLink,
  Loader2,
  MessageCircleQuestion,
  PackagePlus,
  PlayCircle,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { TOOL_LABEL } from "@/components/builder-chat/turn";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ko } from "@/i18n/ko";
import type { AskUser, MarketSuggestion, TestResult, ToolCallRecord } from "@/lib/api/types";
import { cn } from "@/lib/cn";

function CallIcon({ call }: { call: ToolCallRecord }) {
  if (call.ok === undefined)
    return <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-500" />;
  if (call.ok) return <Check className="h-3.5 w-3.5 text-emerald-600" />;
  return <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />;
}

export function ToolCallCard({ call }: { call: ToolCallRecord }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="text-xs">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left hover:bg-slate-100"
      >
        <CallIcon call={call} />
        <span className="font-medium text-slate-700">{TOOL_LABEL[call.name] ?? call.name}</span>
        {call.summary && <span className="truncate text-slate-500">{call.summary}</span>}
      </button>
      {open && <DataView value={call.input ?? {}} className="mx-2 mb-1 max-h-40" />}
    </div>
  );
}

/** 빌더가 한 일들. 많으면 요약 한 줄로 접어 둔다. */
export function ToolCallGroup({ calls, busy }: { calls: ToolCallRecord[]; busy: boolean }) {
  const failed = calls.filter((c) => c.ok === false).length;
  const [open, setOpen] = useState(calls.length <= 3);
  const isOpen = open || busy;
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/70">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-slate-600"
      >
        {busy ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-500" />
        ) : (
          <Check className="h-3.5 w-3.5 text-emerald-600" />
        )}
        <span className="font-medium">
          {busy ? "작업하고 있어요" : `작업 ${calls.length}개 완료`}
          {failed > 0 && <span className="ml-1 text-amber-700">(다시 시도 {failed})</span>}
        </span>
        <ChevronDown
          className={cn("ml-auto h-3.5 w-3.5 transition-transform", isOpen && "rotate-180")}
        />
      </button>
      {isOpen && (
        <div className="space-y-0.5 border-t border-slate-200 px-1 py-1">
          {calls.map((c) => (
            <ToolCallCard key={c.id} call={c} />
          ))}
        </div>
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
    <div className="rounded-xl border border-indigo-200 bg-indigo-50/60 px-4 py-3">
      <p className="flex items-start gap-2 text-sm font-medium text-indigo-950">
        <MessageCircleQuestion className="mt-0.5 h-4 w-4 shrink-0 text-indigo-500" />
        {ask.question}
      </p>
      {ask.options.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1.5 pl-6">
          {ask.options.map((o) => (
            <button
              key={o}
              type="button"
              disabled={!active}
              onClick={() => onPick(o)}
              className="rounded-full border border-indigo-200 bg-white px-3 py-1 text-[13px] font-medium text-indigo-700 shadow-sm transition-colors hover:bg-indigo-600 hover:text-white disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-white disabled:hover:text-indigo-700"
            >
              {o}
            </button>
          ))}
        </div>
      )}
      {active && ask.options.length > 0 && (
        <p className="mt-2 pl-6 text-[11px] text-indigo-500">고르거나 아래에 직접 적어도 돼요.</p>
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
    <div className="rounded-xl border border-emerald-200 bg-white px-4 py-3 shadow-card">
      <div className="flex items-start gap-3">
        <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600">
          <PackagePlus className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-medium text-emerald-700">
            필요한 확장 · {ko.marketTypes[item.type] ?? item.type}
          </p>
          <p className="text-sm font-semibold text-slate-900">{item.name}</p>
          <p className="text-xs text-slate-500">{reason || item.summary}</p>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        {item.installed ? (
          <span className="text-xs text-emerald-700">이미 설치되어 있어요.</span>
        ) : canInstall ? (
          <Button size="sm" disabled={!active || installing} onClick={onInstall}>
            {installing ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> 설치 중…
              </>
            ) : item.price > 0 ? (
              `설치하기 (${item.price}원, 모의 결제)`
            ) : (
              "설치하고 계속하기"
            )}
          </Button>
        ) : (
          <span className="text-xs text-slate-500">
            설치는 관리자만 할 수 있어요. 관리자에게 요청해 주세요.
          </span>
        )}
        <Link
          to={`/market/${item.key}`}
          className="ml-auto inline-flex items-center gap-1 text-xs text-slate-500 hover:text-indigo-600"
        >
          자세히 <ExternalLink className="h-3 w-3" />
        </Link>
      </div>
    </div>
  );
}

export function TestResultCard({ result }: { result: TestResult }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-card">
      <div className="flex items-center gap-2">
        <PlayCircle className="h-4 w-4 text-slate-400" />
        <span className="text-xs font-medium text-slate-500">테스트 실행</span>
        <StatusBadge status={result.status} />
        <Link
          to={`/runs/${result.run_id}`}
          className="ml-auto text-xs text-slate-500 hover:text-indigo-600"
        >
          상세 보기
        </Link>
      </div>
      {result.output?.text && (
        <p className="mt-2 whitespace-pre-wrap rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-800">
          {result.output.text}
        </p>
      )}
      {result.error && <p className="mt-2 text-xs text-red-700">{result.error}</p>}
    </div>
  );
}
