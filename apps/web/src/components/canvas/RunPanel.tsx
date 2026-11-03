import { useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/ui/badge";
import type { GraphNode, Run, RunStep } from "@/lib/api/types";
import { formatCost } from "@/lib/cn";

export function JsonView({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-slate-400">-</span>;
  return (
    <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded bg-slate-50 p-2 text-[11px] text-slate-700">
      {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function StepRow({ step, label }: { step: RunStep; label: string }) {
  const [open, setOpen] = useState(step.status === "failed");
  return (
    <li className="border-b border-slate-100 last:border-0">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-slate-50"
        onClick={() => setOpen((o) => !o)}
      >
        <StatusBadge status={step.status} />
        <span className="font-medium">{label}</span>
        <span className="text-slate-400">{step.node_id}</span>
        <span className="ml-auto text-slate-400">{open ? "접기" : "자세히"}</span>
      </button>
      {open && (
        <div className="grid gap-2 px-3 pb-2 md:grid-cols-2">
          <div>
            <p className="mb-0.5 text-[11px] font-medium text-slate-500">입력</p>
            <JsonView value={step.input} />
          </div>
          <div>
            <p className="mb-0.5 text-[11px] font-medium text-slate-500">출력</p>
            <JsonView value={step.output} />
          </div>
          {step.logs && (
            <div className="md:col-span-2">
              <p className="mb-0.5 text-[11px] font-medium text-slate-500">기록</p>
              <JsonView value={step.logs} />
            </div>
          )}
        </div>
      )}
    </li>
  );
}

export function RunPanel({
  run,
  steps,
  nodes,
}: {
  run: Run | null;
  steps: RunStep[];
  nodes: GraphNode[];
}) {
  const labelOf = (id: string) =>
    (nodes.find((n) => n.id === id)?.data.label as string | undefined) ?? id;
  if (!run) {
    return (
      <p className="px-3 py-4 text-xs text-slate-500">
        &apos;테스트 실행&apos;을 누르면 각 단계의 진행 상황이 여기에 보여요.
      </p>
    );
  }
  return (
    <div className="text-xs">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-3 py-2">
        <StatusBadge status={run.status} />
        <Link to={`/runs/${run.id}`} className="text-indigo-600 hover:underline">
          실행 상세 보기
        </Link>
        <span className="text-slate-400">
          토큰 {run.token_usage?.input_tokens ?? 0}/{run.token_usage?.output_tokens ?? 0} · 비용{" "}
          {formatCost(run.cost)}
        </span>
        {run.status === "waiting_approval" && (
          <span className="text-amber-700">
            사람 승인을 기다리고 있어요. 실행 상세에서 승인하세요.
          </span>
        )}
      </div>
      {run.error && (
        <div className="border-b border-red-100 bg-red-50 px-3 py-2 text-red-800">{run.error}</div>
      )}
      {run.output?.text && (
        <div className="border-b border-slate-100 px-3 py-2">
          <p className="text-[11px] font-medium text-slate-500">결과</p>
          <p className="whitespace-pre-wrap text-sm text-slate-900">{run.output.text}</p>
        </div>
      )}
      <ul>
        {steps.map((s) => (
          <StepRow key={s.id} step={s} label={labelOf(s.node_id)} />
        ))}
      </ul>
    </div>
  );
}
