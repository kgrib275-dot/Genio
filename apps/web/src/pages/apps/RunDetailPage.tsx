import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { RotateCcw } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { FailureBox, JsonView, StepRow, StoryList } from "@/components/canvas/RunPanel";
import { DataView } from "@/components/DataView";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { useApproveRun, useRun } from "@/lib/api/apps";
import { useRerun } from "@/lib/api/v4";
import { canEdit, useSession } from "@/store/session";
import { streamRunEvents } from "@/lib/api/builder";
import type { Run, RunDetail, RunStep } from "@/lib/api/types";
import { formatCost, formatDate } from "@/lib/cn";
import { useListControls } from "@/lib/useListControls";
import { RUN_STATUS } from "@/lib/runLabels";
import { useRerunFromNode, type RunDetailStory, type StoryStep } from "@/lib/api/v5c";
import { PageContainer } from "@/app/Layout";

const TERMINAL = new Set(["succeeded", "failed"]);

type Editable = string | number | boolean;
const isEditable = (v: unknown): v is Editable =>
  typeof v === "string" || typeof v === "number" || typeof v === "boolean";

/** 지난 실행의 입력을 고쳐(또는 그대로) 같은 버전으로 다시 실행한다. JSON 대신 칸으로 고친다. */
function RerunDialog({ run, open, onClose }: { run: Run; open: boolean; onClose: () => void }) {
  const rerun = useRerun(run.app_id);
  const navigate = useNavigate();
  const original = (run.input ?? {}) as Record<string, unknown>;
  const [values, setValues] = useState<Record<string, unknown>>(original);
  useEffect(() => {
    if (open) setValues(original);
    // 열 때마다 원래 입력으로 되돌린다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const keys = Object.keys(original).filter((k) => !k.startsWith("__"));
  const changed = JSON.stringify(values) !== JSON.stringify(original);

  const submit = () =>
    rerun.mutate(
      { runId: run.id, input: changed ? values : undefined },
      {
        onSuccess: (r) => {
          toast.success("다시 실행했어요. 새 실행으로 이동해요.");
          onClose();
          navigate(`/runs/${r.id}`);
        },
      },
    );

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="다시 실행"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            취소
          </Button>
          <Button onClick={submit} disabled={rerun.isPending}>
            <RotateCcw className="h-3.5 w-3.5" />
            {rerun.isPending
              ? "실행하는 중…"
              : changed
                ? "고친 입력으로 실행"
                : "같은 입력으로 실행"}
          </Button>
        </>
      }
    >
      <p className="mb-3 text-sm text-slate-500">
        이 실행과 같은 버전으로 다시 실행해요. 입력을 고쳐서 실행할 수도 있어요.
      </p>
      {keys.length === 0 && <p className="text-sm text-slate-500">입력 값이 없는 실행이에요.</p>}
      <div className="space-y-3">
        {keys.map((k) => {
          const v = values[k];
          return (
            <label key={k} className="block space-y-1">
              <span className="text-xs font-medium text-slate-600">{k}</span>
              {typeof v === "boolean" ? (
                <span className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={v}
                    onChange={(e) => setValues({ ...values, [k]: e.target.checked })}
                    className="accent-indigo-600"
                  />
                  {v ? "예" : "아니오"}
                </span>
              ) : typeof v === "number" ? (
                <Input
                  type="number"
                  value={String(v)}
                  onChange={(e) => setValues({ ...values, [k]: Number(e.target.value) })}
                />
              ) : isEditable(v) ? (
                String(v).length > 60 || String(v).includes("\n") ? (
                  <Textarea
                    value={String(v)}
                    onChange={(e) => setValues({ ...values, [k]: e.target.value })}
                  />
                ) : (
                  <Input
                    value={String(v)}
                    onChange={(e) => setValues({ ...values, [k]: e.target.value })}
                  />
                )
              ) : (
                <>
                  <DataView value={v} className="max-h-40" />
                  <span className="block text-[11px] text-slate-400">
                    여러 값이 묶인 항목이라 그대로 다시 써요.
                  </span>
                </>
              )}
            </label>
          );
        })}
      </div>
      <ErrorBox error={rerun.error} />
    </Dialog>
  );
}

export default function RunDetailPage() {
  const { id: runId = "" } = useParams();
  const run = useRun(runId);
  const approve = useApproveRun(runId);
  const qc = useQueryClient();
  const [comment, setComment] = useState("");
  const [rerunOpen, setRerunOpen] = useState(false);
  const role = useSession((s) => s.role);
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
  const r = run.data as RunDetailStory | undefined;
  if (!r) return null;

  const nodes = r.graph?.nodes ?? [];
  const labelOf = (id: string) =>
    ((nodes.find((n) => n.id === id)?.data as Record<string, unknown> | undefined)?.label as
      string | undefined) ?? id;
  const steps: StoryStep[] = [...r.steps].sort((a, b) =>
    (a.started_at ?? "").localeCompare(b.started_at ?? ""),
  );

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
        {canEdit(role) && TERMINAL.has(r.status) && (
          <Button
            size="sm"
            variant="outline"
            className="ml-auto"
            onClick={() => setRerunOpen(true)}
          >
            <RotateCcw className="h-3.5 w-3.5" /> 다시 실행
          </Button>
        )}
      </div>
      <RerunDialog run={r} open={rerunOpen} onClose={() => setRerunOpen(false)} />

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

      {r.status === "failed" ? (
        <div className="mb-4 overflow-hidden rounded-md border border-red-200 text-sm">
          <FailureBox run={r} steps={steps} appId={canEdit(role) ? r.app_id : undefined} />
        </div>
      ) : (
        r.error && (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
            {r.error}
          </div>
        )
      )}

      {(r.story?.length ?? 0) > 0 && (
        <Card className="mb-6">
          <CardHeader
            title="이번 실행 이야기"
            description="단계마다 무엇을 했는지 한 문장으로 보여 줘요."
          />
          <CardBody className="p-0 text-sm">
            <StoryList story={r.story ?? []} />
          </CardBody>
        </Card>
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
      <StepsCard
        steps={steps}
        labelOf={labelOf}
        runId={r.id}
        appId={r.app_id}
        canRerun={canEdit(role) && TERMINAL.has(r.status)}
      />
    </PageContainer>
  );
}

/** 단계별 진행: 단계 이름 검색, 상태 필터, 개수. 단계마다 문장 설명과 '이 단계부터 다시' */
function StepsCard({
  steps,
  labelOf,
  runId,
  appId,
  canRerun,
}: {
  steps: StoryStep[];
  labelOf: (id: string) => string;
  runId: string;
  appId: string;
  canRerun: boolean;
}) {
  const navigate = useNavigate();
  const rerun = useRerunFromNode(appId);
  const sc = useListControls(steps, {
    key: "run-steps",
    search: (s) => `${labelOf(s.node_id)} ${s.node_id} ${s.summary ?? ""}`,
    filters: [
      {
        id: "status",
        label: "상태",
        options: Object.entries(RUN_STATUS).map(([value, label]) => ({ value, label })),
        match: (s, v) => s.status === v,
      },
    ],
  });
  return (
    <Card className="mt-6">
      <CardHeader title="단계별 진행" />
      {steps.length > 0 && (
        <ListToolbar c={sc} placeholder="단계 이름·내용으로 찾기" className="px-4 pb-3 sm:px-5" />
      )}
      <NoMatch c={sc} />
      <ul className="border-t border-slate-100">
        {sc.pageItems.map((s) => (
          <StepRow
            key={s.id}
            step={s}
            label={labelOf(s.node_id)}
            rerunPending={rerun.isPending}
            onRerunFrom={
              canRerun && s.status !== "skipped"
                ? () =>
                    rerun.mutate(
                      { runId, fromNode: s.node_id },
                      {
                        onSuccess: (r) => {
                          toast.success(`'${labelOf(s.node_id)}' 단계부터 다시 실행했어요.`);
                          navigate(`/runs/${r.id}`);
                        },
                        onError: (err) => toast.error(err),
                      },
                    )
                : undefined
            }
          />
        ))}
        {steps.length === 0 && (
          <li className="px-5 py-4 text-sm text-slate-500">아직 진행된 단계가 없어요.</li>
        )}
      </ul>
      {steps.length > 0 && (
        <ListPager c={sc} className="border-t border-slate-100 px-4 py-2 sm:px-5" />
      )}
    </Card>
  );
}
