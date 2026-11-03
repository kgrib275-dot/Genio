import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { JsonView, StepRow } from "@/components/canvas/RunPanel";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { useApproveRun, useRun } from "@/lib/api/apps";
import { streamRunEvents } from "@/lib/api/builder";
import type { Run, RunDetail, RunStep } from "@/lib/api/types";
import { formatCost, formatDate } from "@/lib/cn";
import { PageContainer } from "@/app/Layout";

const TERMINAL = new Set(["succeeded", "failed"]);

export default function RunDetailPage() {
  const { id: runId = "" } = useParams();
  const run = useRun(runId);
  const approve = useApproveRun(runId);
  const qc = useQueryClient();
  const [comment, setComment] = useState("");
  const status = run.data?.status;

  // 끝나지 않은 실행은 SSE로 따라간다.
  useEffect(() => {
    if (!status || TERMINAL.has(status) || status === "waiting_approval") return;
    const ctrl = new AbortController();
    void streamRunEvents(
      runId,
      (ev) => {
        qc.setQueryData<RunDetail>(["run", runId], (old) => {
          if (!old) return old;
          if (ev.event === "step") {
            const step = ev.data as RunStep;
            const others = old.steps.filter((s) => s.id !== step.id);
            return { ...old, steps: [...others, step] };
          }
          if (ev.event === "run" || ev.event === "end") return { ...old, ...(ev.data as Run) };
          return old;
        });
        if (ev.event === "end") void qc.invalidateQueries({ queryKey: ["run", runId] });
      },
      ctrl.signal,
    ).catch(() => undefined);
    return () => ctrl.abort();
  }, [runId, status, qc]);

  if (run.isLoading) return <Loading />;
  if (run.error)
    return (
      <PageContainer>
        <ErrorBox error={run.error} />
      </PageContainer>
    );
  const r = run.data;
  if (!r) return null;

  const nodes = r.graph?.nodes ?? [];
  const labelOf = (id: string) =>
    ((nodes.find((n) => n.id === id)?.data as Record<string, unknown> | undefined)?.label as
      string | undefined) ?? id;
  const steps = [...r.steps].sort((a, b) => (a.started_at ?? "").localeCompare(b.started_at ?? ""));

  const decide = (approved: boolean) =>
    approve.mutate(
      { approved, comment: comment || undefined },
      {
        onSuccess: () => {
          toast.success(approved ? "승인했어요. 흐름이 이어서 실행돼요." : "거절했어요.");
          void qc.invalidateQueries({ queryKey: ["run", runId] });
        },
      },
    );

  return (
    <PageContainer>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Link to={`/apps/${r.app_id}/runs`} className="text-sm text-indigo-600 hover:underline">
          ← 실행 기록
        </Link>
        <h1 className="text-xl font-bold">실행 상세</h1>
        <StatusBadge status={r.status} />
        <span className="text-sm text-slate-500">
          {formatDate(r.created_at)} · 토큰 {r.token_usage?.input_tokens ?? 0}/
          {r.token_usage?.output_tokens ?? 0} · {formatCost(r.cost)}
        </span>
      </div>

      {r.status === "waiting_approval" && r.approval && (
        <Card className="mb-6 border-amber-300">
          <CardHeader title="승인이 필요해요" description={labelOf(r.approval.node_id)} />
          <CardBody className="space-y-3">
            <p className="whitespace-pre-wrap text-sm">{r.approval.message}</p>
            <Textarea
              aria-label="의견"
              placeholder="의견(선택)"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
            <ErrorBox error={approve.error} />
            <div className="flex gap-2">
              <Button disabled={approve.isPending} onClick={() => decide(true)}>
                승인하기
              </Button>
              <Button variant="outline" disabled={approve.isPending} onClick={() => decide(false)}>
                거절하기
              </Button>
            </div>
          </CardBody>
        </Card>
      )}
      {r.approval && r.approval.approved !== undefined && r.approval.approved !== null && (
        <p className="mb-4 text-sm text-slate-600">
          {r.approval.approved ? "승인됨" : "거절됨"}
          {r.approval.comment && ` · 의견: ${r.approval.comment}`}
        </p>
      )}

      {r.error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
          {r.error}
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader title="입력" />
          <CardBody>
            <JsonView value={r.input} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="결과" />
          <CardBody>
            {r.output?.text ? (
              <p className="whitespace-pre-wrap text-sm">{r.output.text}</p>
            ) : (
              <JsonView value={r.output} />
            )}
          </CardBody>
        </Card>
      </div>
      <Card className="mt-6">
        <CardHeader title="단계별 진행" />
        <ul>
          {steps.map((s) => (
            <StepRow key={s.id} step={s} label={labelOf(s.node_id)} />
          ))}
          {steps.length === 0 && (
            <li className="px-5 py-4 text-sm text-slate-500">아직 진행된 단계가 없어요.</li>
          )}
        </ul>
      </Card>
    </PageContainer>
  );
}
