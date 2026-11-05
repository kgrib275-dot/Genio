// v0.8 검색 튜닝: 대표 질문 세트로 검색 설정을 비교하고, 가장 잘 맞는 설정을 한 번에 적용한다.
import { FlaskConical, Plus, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBox } from "@/components/ErrorBox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import type { KbDocumentV2 } from "@/lib/api/types";
import {
  hitText,
  improvement,
  rowLabel,
  useApplyRetrieval,
  useRunTuning,
  useSaveQuestions,
  useTuning,
  type TuningQuestion,
  type TuningResult,
  type TuningRow,
} from "@/lib/api/v8kb";
import { cn, formatDate } from "@/lib/cn";

const BLANK: TuningQuestion = { question: "", expect_keyword: "", expect_document_id: "" };

function sameQuestions(a: TuningQuestion[], b: TuningQuestion[]): boolean {
  return JSON.stringify(a.map(strip)) === JSON.stringify(b.map(strip));
}
function strip(q: TuningQuestion) {
  return [q.question, q.expect_keyword, q.expect_document_id];
}

function ResultTable({
  result,
  onApply,
  applying,
  canApply,
}: {
  result: TuningResult;
  onApply: (row: TuningRow, threshold?: number) => void;
  applying: boolean;
  canApply: boolean;
}) {
  const total = result.questions;
  const rows = [...result.rows].sort(
    (a, b) => b.hit_rate - a.hit_rate || b.avg_top_score - a.avg_top_score,
  );
  return (
    <div className="space-y-3">
      <div className="rounded-lg bg-emerald-50 px-3 py-2.5 text-sm text-emerald-900">
        <p className="flex flex-wrap items-center gap-1.5 font-semibold">
          <Sparkles className="h-4 w-4" /> 가장 좋은 설정: {rowLabel(result.best)}
          <span className="font-normal">· 적중률 {hitText(result.best, total)}</span>
        </p>
        <p className="mt-0.5 text-xs">
          {improvement(result.best, result.current_row)}
          {result.suggested_threshold != null &&
            ` 점수 기준은 ${result.suggested_threshold.toFixed(2)} 정도가 알맞아 보여요.`}
        </p>
        <div className={cn("mt-2 flex flex-wrap gap-2", !canApply && "hidden")}>
          <Button size="sm" disabled={applying} onClick={() => onApply(result.best)}>
            이 설정으로 적용
          </Button>
          {result.suggested_threshold != null && (
            <Button
              size="sm"
              variant="outline"
              disabled={applying}
              onClick={() => onApply(result.best, result.suggested_threshold ?? undefined)}
            >
              점수 기준 {result.suggested_threshold.toFixed(2)}까지 같이 적용
            </Button>
          )}
        </div>
      </div>
      {result.truncated && (
        <p className="text-xs text-amber-700">
          시간이 길어져 일부 조합은 계산하지 못했어요. 질문 수를 줄여 다시 실행해 보세요.
        </p>
      )}
      {Object.entries(result.errors).map(([k, msg]) => (
        <p key={k} className="text-xs text-red-600">
          {k} 방식은 계산하지 못했어요: {msg}
        </p>
      ))}
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full min-w-[34rem] text-left text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr>
              <th className="px-3 py-2 font-medium">설정</th>
              <th className="px-3 py-2 font-medium">적중률</th>
              <th className="px-3 py-2 font-medium">평균 최고 점수</th>
              <th className="px-3 py-2 font-medium">평균 시간</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {result.current_row && (
              <tr className="bg-slate-50/60">
                <td className="px-3 py-2">
                  {rowLabel(result.current_row)} <Badge tone="gray">지금 설정</Badge>
                </td>
                <td className="px-3 py-2">{hitText(result.current_row, total)}</td>
                <td className="px-3 py-2">{result.current_row.avg_top_score.toFixed(3)}</td>
                <td className="px-3 py-2">{Math.round(result.current_row.avg_ms)}ms</td>
                <td />
              </tr>
            )}
            {rows.map((r) => (
              <tr
                key={`${r.method}-${r.top_k}-${r.rerank}`}
                className={cn(r.is_best && "bg-emerald-50/70 font-medium")}
              >
                <td className="px-3 py-2">
                  {rowLabel(r)} {r.is_best && <Badge tone="green">가장 좋음</Badge>}
                  {r.is_current && <Badge tone="gray">지금 설정</Badge>}
                </td>
                <td className="px-3 py-2">
                  <span className="inline-flex items-center gap-2">
                    <span className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
                      <span
                        className="block h-full rounded-full bg-indigo-500"
                        style={{ width: `${Math.round(r.hit_rate * 100)}%` }}
                      />
                    </span>
                    {hitText(r, total)}
                  </span>
                </td>
                <td className="px-3 py-2">{r.avg_top_score.toFixed(3)}</td>
                <td className="px-3 py-2">{Math.round(r.avg_ms)}ms</td>
                <td className="px-3 py-2 text-right">
                  {canApply && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={applying}
                      aria-label={`${rowLabel(r)} 적용`}
                      onClick={() => onApply(r)}
                    >
                      적용
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-slate-500">
        {formatDate(result.at)} · 질문 {total}개 · 점수 기준 {result.threshold}. 적중률은 정답이
        상위 몇 개 안에 들어온 질문의 비율이에요. 같은 방식은 검색을 한 번만 하고 3·5·8개로 잘라
        계산해요.
      </p>
    </div>
  );
}

export function TuningCard({
  kbId,
  docs,
  editable,
}: {
  kbId: string;
  docs: KbDocumentV2[];
  editable: boolean;
}) {
  const state = useTuning(kbId);
  const save = useSaveQuestions(kbId);
  const run = useRunTuning(kbId);
  const apply = useApplyRetrieval(kbId);
  const [qs, setQs] = useState<TuningQuestion[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [rerank, setRerank] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const saved = state.data?.questions ?? [];
  const max = state.data?.max_questions ?? 30;

  useEffect(() => {
    if (state.data && !loaded) {
      setQs(state.data.questions.length ? state.data.questions : []);
      setLoaded(true);
    }
  }, [state.data, loaded]);

  const dirty = loaded && !sameQuestions(qs, saved);
  const ready = qs.filter(
    (q) => q.question.trim() && (q.expect_keyword.trim() || q.expect_document_id),
  );
  const est = state.data?.estimate;
  const set = (i: number, patch: Partial<TuningQuestion>) =>
    setQs((list) => list.map((q, j) => (j === i ? { ...q, ...patch } : q)));

  const doSave = () =>
    save.mutate(ready, {
      onSuccess: (r) => {
        setQs(r.questions);
        toast.success("대표 질문을 저장했어요.");
      },
    });

  return (
    <Card>
      <CardHeader
        title="검색 튜닝"
        description="자주 묻는 질문과 정답이 들어 있어야 할 문서·낱말을 적어 두면, 검색 설정을 바꿔 가며 어떤 설정이 잘 찾는지 비교해 줘요."
      />
      <CardBody className="space-y-4">
        <ErrorBox error={state.error} />
        {loaded && qs.length === 0 && (
          <EmptyState
            compact
            icon={<FlaskConical className="h-5 w-5" />}
            title="대표 질문을 넣어 보세요"
            description="예: 질문 '연차는 며칠인가요?' → 정답 낱말 '15일'. 5~10개면 충분해요."
            action={
              editable
                ? {
                    label: "질문 추가",
                    onClick: () => setQs([{ ...BLANK }]),
                    icon: <Plus className="h-4 w-4" />,
                  }
                : null
            }
          />
        )}
        {qs.length > 0 && (
          <ul className="space-y-2">
            {qs.map((q, i) => (
              <li
                key={q.id ?? i}
                className="grid gap-2 rounded-lg border border-slate-200 p-2.5 sm:grid-cols-[1fr_9rem_11rem_auto]"
              >
                <Input
                  aria-label={`질문 ${i + 1}`}
                  placeholder="질문(예: 연차는 며칠인가요?)"
                  maxLength={300}
                  disabled={!editable}
                  value={q.question}
                  onChange={(e) => set(i, { question: e.target.value })}
                />
                <Input
                  aria-label={`정답 낱말 ${i + 1}`}
                  placeholder="정답 낱말(예: 15일)"
                  maxLength={100}
                  disabled={!editable}
                  value={q.expect_keyword}
                  onChange={(e) => set(i, { expect_keyword: e.target.value })}
                />
                <Select
                  aria-label={`정답 문서 ${i + 1}`}
                  disabled={!editable}
                  value={q.expect_document_id}
                  onChange={(e) => set(i, { expect_document_id: e.target.value })}
                >
                  <option value="">문서 지정 안 함</option>
                  {docs.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.filename}
                    </option>
                  ))}
                </Select>
                {editable && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-red-600"
                    aria-label={`질문 ${i + 1} 지우기`}
                    onClick={() => setQs((list) => list.filter((_, j) => j !== i))}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        {editable && qs.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={qs.length >= max}
              onClick={() => setQs((list) => [...list, { ...BLANK }])}
            >
              <Plus className="h-3.5 w-3.5" /> 질문 추가({qs.length}/{max})
            </Button>
            <Button
              size="sm"
              disabled={!dirty || save.isPending || ready.length === 0}
              onClick={doSave}
            >
              {save.isPending ? "저장하는 중…" : "질문 저장"}
            </Button>
            {qs.length !== ready.length && (
              <span className="text-xs text-amber-700">
                질문과 정답(낱말이나 문서)이 모두 있는 것만 저장돼요.
              </span>
            )}
          </div>
        )}
        <ErrorBox error={save.error} />

        {editable && saved.length > 0 && (
          <div className="space-y-2 rounded-lg border border-slate-200 bg-slate-50/60 p-3 text-sm">
            <p className="font-medium text-slate-800">튜닝 실행</p>
            <p className="text-xs text-slate-500">
              질문 {saved.length}개 × 검색 방식 3가지 = 검색 약 {est?.searches ?? 0}번(임베딩 약{" "}
              {est?.embedding_calls ?? 0}번)을 하고 {est?.combos ?? 9}가지 조합을 비교해요.
            </p>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={rerank}
                onChange={(e) => {
                  setRerank(e.target.checked);
                  if (!e.target.checked) setConfirm(false);
                }}
              />
              다시 순위 매기기(재정렬)도 비교
            </label>
            {rerank && (
              <div className="ml-6 space-y-1 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
                <p>
                  재정렬은 AI를 질문마다 한 번씩 더 불러요. 이번에 약{" "}
                  <b>{est?.with_rerank.rerank_llm_calls ?? 0}번</b> 더 부르고 비용이 들어요(조합{" "}
                  {est?.with_rerank.combos ?? 12}가지).
                </p>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={confirm}
                    onChange={(e) => setConfirm(e.target.checked)}
                  />
                  비용을 알고 실행할게요
                </label>
              </div>
            )}
            <Button
              disabled={run.isPending || dirty || (rerank && !confirm)}
              onClick={() =>
                run.mutate(
                  { include_rerank: rerank, confirm_rerank: confirm },
                  { onSuccess: () => toast.success("튜닝이 끝났어요. 아래 표를 확인하세요.") },
                )
              }
            >
              <FlaskConical className="h-4 w-4" /> {run.isPending ? "비교하는 중…" : "튜닝 실행"}
            </Button>
            {dirty && <p className="text-xs text-amber-700">바꾼 질문을 먼저 저장해 주세요.</p>}
            <ErrorBox error={run.error} />
          </div>
        )}

        {state.data?.last_run && (
          <ResultTable
            result={state.data.last_run}
            applying={apply.isPending}
            canApply={editable}
            onApply={
              editable
                ? (row, threshold) =>
                    apply.mutate(
                      {
                        method: row.method,
                        top_k: row.top_k,
                        rerank: row.rerank,
                        ...(threshold != null ? { score_threshold: threshold } : {}),
                      },
                      {
                        onSuccess: () =>
                          toast.success(
                            `'${rowLabel(row)}' 설정을 적용했어요. 검색 시험에서 확인해 보세요.`,
                          ),
                        onError: (e) => toast.error(e),
                      },
                    )
                : () => undefined
            }
          />
        )}
      </CardBody>
    </Card>
  );
}
