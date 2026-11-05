import { RotateCcw, Wand2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { DataView } from "@/components/DataView";
import { inspectorSteps } from "@/components/run/inspectorSteps";
import { ValueInspector } from "@/components/run/ValueInspector";
import { StatusBadge } from "@/components/ui/badge";
import { toast } from "@/components/ui/toast-store";
import { useRun } from "@/lib/api/apps";
import type { GraphNode, Run, RunStep } from "@/lib/api/types";
import { splitFailure, useRerunFromNode, type RunDetailStory, type StoryStep } from "@/lib/api/v5c";
import { formatCost } from "@/lib/cn";

const TERMINAL = new Set(["succeeded", "failed", "waiting_approval"]);

/** 실행 입력·출력 등 데이터를 읽기 쉬운 목록으로(원본 보기 가능) */
export function JsonView({ value }: { value: unknown }) {
  return <DataView value={value} />;
}

/** 단계 한 줄: 문장 설명을 먼저 보여 주고, '자세히'를 누르면 입력·출력 데이터를 펼친다 */
export function StepRow({
  step,
  label,
  onRerunFrom,
  rerunPending,
}: {
  step: StoryStep;
  label: string;
  onRerunFrom?: () => void;
  rerunPending?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const failed = step.status === "failed";
  const summary = step.summary?.split("\n") ?? [];
  return (
    <li className="border-b border-slate-100 last:border-0">
      <div className="flex w-full items-start gap-2 px-3 py-1.5 text-xs">
        <StatusBadge status={step.status} />
        <div className="min-w-0 flex-1">
          {summary.length > 0 ? (
            <>
              <p className={failed ? "font-medium text-red-800" : "text-slate-800"}>{summary[0]}</p>
              {summary.slice(1).map((line, i) => (
                <p key={i} className="text-red-700">
                  {line}
                </p>
              ))}
            </>
          ) : (
            <p className="font-medium text-slate-800">{label}</p>
          )}
        </div>
        {onRerunFrom && (
          <button
            type="button"
            disabled={rerunPending}
            onClick={onRerunFrom}
            title="앞 단계 결과는 그대로 두고 이 단계부터 다시 실행해요"
            className="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-slate-500 hover:bg-slate-100 hover:text-indigo-700 disabled:opacity-40"
          >
            <RotateCcw className="h-3 w-3" />
            <span className="hidden sm:inline">이 단계부터 다시</span>
          </button>
        )}
        <button
          type="button"
          className="shrink-0 rounded px-1.5 py-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-label={`${label} 자세히`}
        >
          {open ? "접기" : "자세히"}
        </button>
      </div>
      {open && (
        <div className="grid gap-2 px-3 pb-2 md:grid-cols-2">
          <div>
            <p className="mb-0.5 text-[11px] font-medium text-slate-500">설정</p>
            <JsonView value={step.input} />
          </div>
          <div>
            <p className="mb-0.5 text-[11px] font-medium text-slate-500">결과</p>
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

/** 실패했을 때: 무엇이 문제 + 어떻게 하면 되는지(두 줄) + 빌더에게 고쳐 달라고 하기 */
export function FailureBox({
  run,
  steps,
  appId,
}: {
  run: Pick<Run, "id" | "error">;
  steps: StoryStep[];
  appId?: string;
}) {
  const navigate = useNavigate();
  const failed = steps.find((s) => s.status === "failed");
  const { problem, fix } = splitFailure(failed?.summary, run.error);
  return (
    <div className="flex flex-wrap items-start gap-2 border-b border-red-100 bg-red-50 px-3 py-2 text-red-900">
      <div className="min-w-0 flex-1">
        <p className="font-medium">{problem}</p>
        <p className="text-red-800">{fix}</p>
      </div>
      {appId && (
        <button
          type="button"
          onClick={() => navigate(`/apps/${appId}/builder?fix=${run.id}`)}
          className="inline-flex shrink-0 items-center gap-1 rounded-md border border-red-200 bg-white px-2 py-1 text-xs font-medium text-red-800 hover:bg-red-100"
        >
          <Wand2 className="h-3.5 w-3.5" /> 빌더에게 고쳐 달라고 하기
        </button>
      )}
    </div>
  );
}

/** 실행 이야기: 단계마다 한 문장(기능 정의서 S3) */
export function StoryList({ story }: { story: string[] }) {
  if (story.length === 0) return null;
  return (
    <ol className="space-y-0.5 border-b border-slate-100 px-3 py-2">
      {story.map((line, i) => (
        <li key={i} className="flex gap-2 text-xs text-slate-700">
          <span className="w-4 shrink-0 text-right text-slate-400">{i + 1}</span>
          <span className="whitespace-pre-wrap">{line}</span>
        </li>
      ))}
    </ol>
  );
}

export function RunPanel({
  run,
  steps,
  nodes,
  selectedId,
}: {
  run: Run | null;
  steps: RunStep[];
  nodes: GraphNode[];
  /** 캔버스에서 고른 단계(값 확인창에서 먼저 펼친다) */
  selectedId?: string | null;
}) {
  const navigate = useNavigate();
  const ended = Boolean(run && TERMINAL.has(run.status));
  // 끝난 실행은 상세(문장 설명 포함)를 다시 받아 온다
  const detail = useRun(ended && run ? run.id : "");
  const rerun = useRerunFromNode(run?.app_id);
  const labelOf = (id: string) =>
    (nodes.find((n) => n.id === id)?.data.label as string | undefined) ?? id;
  if (!run) {
    return (
      <p className="px-3 py-4 text-xs text-slate-500">
        &apos;테스트 실행&apos;을 누르면 각 단계의 진행 상황이 여기에 보여요.
      </p>
    );
  }
  const d = detail.data as RunDetailStory | undefined;
  const fresh = d && d.id === run.id ? d : undefined;
  const rows: StoryStep[] = fresh ? fresh.steps : steps;
  const rerunFrom = (nodeId: string) =>
    rerun.mutate(
      { runId: run.id, fromNode: nodeId },
      {
        onSuccess: (r) => {
          toast.success(`'${labelOf(nodeId)}' 단계부터 다시 실행했어요.`);
          navigate(`/runs/${r.id}`);
        },
        onError: (err) => toast.error(err),
      },
    );
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
      {run.status === "failed" && <FailureBox run={run} steps={rows} appId={run.app_id} />}
      {run.output?.text && (
        <div className="border-b border-slate-100 px-3 py-2">
          <p className="text-[11px] font-medium text-slate-500">결과</p>
          <p className="whitespace-pre-wrap text-sm text-slate-900">{run.output.text}</p>
        </div>
      )}
      <ul>
        {rows.map((s) => (
          <StepRow
            key={s.id}
            step={s}
            label={labelOf(s.node_id)}
            rerunPending={rerun.isPending}
            onRerunFrom={
              ended && run.status !== "waiting_approval" && s.status !== "skipped"
                ? () => rerunFrom(s.node_id)
                : undefined
            }
          />
        ))}
      </ul>
      <details className="border-t border-slate-100">
        <summary className="cursor-pointer px-3 py-2 font-medium text-slate-700">
          값 확인창(단계별 값 찾기·복사)
        </summary>
        <ValueInspector
          steps={inspectorSteps(rows, labelOf)}
          focusNodeId={selectedId ?? undefined}
        />
      </details>
    </div>
  );
}
