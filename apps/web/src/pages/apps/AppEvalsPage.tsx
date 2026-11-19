// 후속(O1): 평가 — 질문과 '이런 답이어야 해요' 조건을 모아 한 번에 돌리고 점수를 본다
import { AlertTriangle, CheckCircle2, Play, Plus, Trash2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { useApp } from "@/lib/api/apps";
import {
  formatRate,
  splitTerms,
  useEvalCases,
  useEvalGate,
  useSaveEvalGate,
  useEvalHistory,
  useEvalReport,
  useRunEval,
  useSaveEvalCases,
  type EvalCase,
} from "@/lib/api/evals";
import { cn } from "@/lib/cn";
import { AppNav } from "@/pages/apps/AppNav";
import { canEdit, useSession } from "@/store/session";

function newCase(): EvalCase {
  return {
    id: "",
    name: "",
    input: { message: "" },
    contains: [],
    not_contains: [],
    max_seconds: null,
    json_valid: false,
  };
}

function CaseEditor({
  cases,
  readOnly,
  saving,
  onSave,
}: {
  cases: EvalCase[];
  readOnly: boolean;
  saving: boolean;
  onSave: (c: EvalCase[]) => void;
}) {
  const [rows, setRows] = useState<EvalCase[]>(cases);
  // 처음에는 빈 질문 칸 하나를 미리 보여 줘서 바로 적을 수 있게 한다
  useEffect(
    () => setRows(cases.length === 0 && !readOnly ? [newCase()] : cases),
    [cases, readOnly],
  );
  const set = (i: number, patch: Partial<EvalCase>) =>
    setRows((r) => r.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  return (
    <Card>
      <CardHeader
        title="점검 질문"
        description="질문과 '꼭 들어가야 하는 말', '들어가면 안 되는 말'을 적어 두면 답이 맞는지 규칙으로 채점해요. 챗 앱은 질문 칸에, 흐름 앱은 입력 값 이름과 값에 적어요."
      />
      <CardBody className="space-y-3">
        {rows.length === 0 && (
          <p className="text-sm text-slate-500">
            질문을 적고 저장하세요. 질문이 더 필요하면 아래 &apos;질문 추가&apos;를 누르세요.
          </p>
        )}
        {rows.map((c, i) => {
          const message = String(c.input.message ?? "");
          return (
            <div
              key={c.id || `new-${i}`}
              className="space-y-2 rounded-lg border border-slate-200 p-3"
            >
              <div className="flex items-center gap-2">
                <Input
                  aria-label={`질문 ${i + 1} 이름`}
                  placeholder="이름(예: 환불 기간)"
                  value={c.name}
                  disabled={readOnly}
                  maxLength={100}
                  onChange={(e) => set(i, { name: e.target.value })}
                />
                {!readOnly && (
                  <button
                    type="button"
                    aria-label={`질문 ${i + 1} 지우기`}
                    className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                    onClick={() => setRows((r) => r.filter((_, j) => j !== i))}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                )}
              </div>
              <Textarea
                aria-label={`질문 ${i + 1} 내용`}
                rows={2}
                placeholder="사용자가 보낼 질문"
                value={message}
                disabled={readOnly}
                onChange={(e) => set(i, { input: { ...c.input, message: e.target.value } })}
              />
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="space-y-1 text-xs">
                  <span className="font-medium text-slate-600">
                    꼭 들어가야 하는 말(쉼표로 구분)
                  </span>
                  <Input
                    aria-label={`질문 ${i + 1} 꼭 들어갈 말`}
                    value={c.contains.join(", ")}
                    disabled={readOnly}
                    onChange={(e) => set(i, { contains: splitTerms(e.target.value) })}
                  />
                </label>
                <label className="space-y-1 text-xs">
                  <span className="font-medium text-slate-600">들어가면 안 되는 말</span>
                  <Input
                    aria-label={`질문 ${i + 1} 없어야 할 말`}
                    value={c.not_contains.join(", ")}
                    disabled={readOnly}
                    onChange={(e) => set(i, { not_contains: splitTerms(e.target.value) })}
                  />
                </label>
              </div>
              <label className="block space-y-1 text-xs">
                <span className="font-medium text-slate-600">
                  AI가 따로 확인할 기준(선택) — 말로 적으세요
                </span>
                <Input
                  aria-label={`질문 ${i + 1} AI 심판 기준`}
                  placeholder="예: 연차 일수를 정확히 말하고, 모르면 모른다고 답한다"
                  value={c.judge ?? ""}
                  disabled={readOnly}
                  onChange={(e) => set(i, { judge: e.target.value })}
                />
              </label>
              <div className="flex flex-wrap items-center gap-4 text-xs text-slate-600">
                <label className="flex items-center gap-1.5">
                  최대 시간
                  <Input
                    type="number"
                    min={0}
                    className="w-20"
                    aria-label={`질문 ${i + 1} 최대 시간(초)`}
                    value={c.max_seconds ?? ""}
                    disabled={readOnly}
                    onChange={(e) =>
                      set(i, { max_seconds: e.target.value ? Number(e.target.value) : null })
                    }
                  />
                  초
                </label>
                <label className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={c.json_valid}
                    disabled={readOnly}
                    onChange={(e) => set(i, { json_valid: e.target.checked })}
                  />
                  답이 정해진 형식(JSON)이어야 해요
                </label>
              </div>
            </div>
          );
        })}
        {!readOnly && (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setRows((r) => [...r, newCase()])}>
              <Plus className="h-4 w-4" /> 질문 추가
            </Button>
            <Button
              disabled={saving}
              onClick={() =>
                onSave(
                  rows
                    .filter((c) => c.name.trim() || String(c.input.message ?? "").trim())
                    .map((c) => ({
                      ...c,
                      name:
                        c.name.trim() ||
                        String(c.input.message ?? "")
                          .trim()
                          .slice(0, 30),
                    })),
                )
              }
            >
              {saving ? "저장 중…" : "질문 저장"}
            </Button>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function Report({ appId, batch }: { appId: string; batch: string }) {
  const q = useEvalReport(appId, batch);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data;
  if (!d) return null;
  return (
    <div className="space-y-2" data-testid="eval-report">
      <p className="text-sm text-slate-700">
        {d.running ? `채점 중… (${d.finished}/${d.total})` : `통과 ${d.passed}/${d.total}`}
        {d.avg_seconds != null && ` · 평균 ${d.avg_seconds}초`}
      </p>
      <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 text-sm">
        {d.results.map((r) => (
          <li key={r.run_id} className="space-y-1 px-3 py-2">
            <div className="flex items-center gap-2">
              {!r.finished ? (
                <span className="text-xs text-slate-400">대기·실행 중</span>
              ) : r.passed ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-label="통과" />
              ) : (
                <XCircle className="h-4 w-4 text-red-600" aria-label="실패" />
              )}
              <span className="font-medium">{r.name}</span>
              <Link
                className="ml-auto text-xs text-indigo-600 hover:underline"
                to={`/runs/${r.run_id}`}
              >
                실행 보기
              </Link>
            </div>
            {r.finished && !r.passed && (
              <ul className="space-y-0.5 pl-6 text-xs text-red-700">
                {r.checks
                  .filter((c) => !c.ok)
                  .map((c) => (
                    <li key={c.name}>
                      {c.name} 못 지켰어요{c.detail ? ` (${c.detail})` : ""}
                    </li>
                  ))}
              </ul>
            )}
            {r.answer && <p className="line-clamp-2 pl-6 text-xs text-slate-500">{r.answer}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function GateCard({ appId, readOnly }: { appId: string; readOnly: boolean }) {
  const gate = useEvalGate(appId);
  const save = useSaveEvalGate(appId);
  const g = gate.data ?? { enabled: false, min_pass_rate: 0.8 };
  const apply = (next: { enabled: boolean; min_pass_rate: number }) =>
    save.mutate(next, {
      onSuccess: () => toast.success("배포 전 조건을 저장했어요."),
      onError: (err) => toast.error(err),
    });
  return (
    <Card className="flex flex-wrap items-center gap-3 p-4">
      <label className="flex items-center gap-2 text-sm font-medium text-slate-800">
        <input
          type="checkbox"
          checked={g.enabled}
          disabled={readOnly || save.isPending}
          onChange={(e) => apply({ ...g, enabled: e.target.checked })}
        />
        배포하기 전에 품질 점검을 통과해야 해요
      </label>
      {g.enabled && (
        <label className="flex items-center gap-1.5 text-xs text-slate-600">
          통과율
          <Input
            type="number"
            min={10}
            max={100}
            className="w-20"
            aria-label="통과해야 하는 비율(%)"
            defaultValue={Math.round(g.min_pass_rate * 100)}
            disabled={readOnly}
            onBlur={(e) =>
              apply({
                ...g,
                min_pass_rate: Math.max(10, Math.min(100, Number(e.target.value) || 80)) / 100,
              })
            }
          />
          % 이상
        </label>
      )}
      <p className="basis-full text-xs text-slate-500">
        켜면 가장 최근 점검의 통과율이 기준보다 낮거나 점검한 적이 없을 때 배포가 멈춰요. AI가
        확인할 기준을 적은 질문은 결과 화면을 열 때 AI가 한 번 판단해요(AI 사용량이 조금 들어요).
      </p>
    </Card>
  );
}

export default function AppEvalsPage() {
  const { id: appId = "" } = useParams();
  const role = useSession((s) => s.role);
  const app = useApp(appId);
  const cases = useEvalCases(appId);
  const save = useSaveEvalCases(appId);
  const history = useEvalHistory(appId);
  const run = useRunEval(appId);
  const [open, setOpen] = useState<string | null>(null);
  const readOnly = !canEdit(role);
  const batches = history.data?.batches ?? [];
  const latest = batches[0];

  return (
    <div className="flex min-h-full flex-col">
      <AppNav appId={appId} title={app.data?.name ?? ""} icon={app.data?.icon} />
      <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6">
        {cases.isLoading && <Loading />}
        <ErrorBox error={cases.error ?? app.error} />
        <GateCard appId={appId} readOnly={readOnly} />
        {latest?.dropped && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              최근 평가 점수가 떨어졌어요({formatRate(latest.previous_pass_rate)} →{" "}
              {formatRate(latest.pass_rate)}). 배포하기 전에 아래에서 어떤 질문이 틀렸는지
              확인하세요.
            </span>
          </div>
        )}
        {cases.data && (
          <CaseEditor
            cases={cases.data.cases}
            readOnly={readOnly}
            saving={save.isPending}
            onSave={(c) =>
              save.mutate(c, {
                onSuccess: () => toast.success("평가 질문을 저장했어요."),
                onError: (err) => toast.error(err),
              })
            }
          />
        )}
        <Card>
          <CardHeader
            title="점검하기"
            description="저장한 질문을 지금 작업본으로 한 번에 실행해 채점해요. 먼저 질문을 저장하세요."
            action={
              !readOnly && (
                <Button
                  disabled={run.isPending || (cases.data?.cases.length ?? 0) === 0}
                  onClick={() =>
                    run.mutate(undefined, {
                      onSuccess: (r) => {
                        setOpen(r.batch);
                        toast.success(`질문 ${r.total}개로 평가를 시작했어요.`);
                      },
                      onError: (err) => toast.error(err),
                    })
                  }
                >
                  <Play className="h-4 w-4" /> 지금 점검하기
                </Button>
              )
            }
          />
          <CardBody className="space-y-3">
            {batches.length === 0 && (
              <p className="text-sm text-slate-500">아직 점검한 적이 없어요.</p>
            )}
            {batches.map((b) => (
              <div key={b.batch}>
                <button
                  type="button"
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left text-sm",
                    open === b.batch ? "border-indigo-300 bg-indigo-50" : "border-slate-200",
                  )}
                  onClick={() => setOpen(open === b.batch ? null : b.batch)}
                >
                  <span className="font-semibold">
                    {b.running ? "채점 중" : formatRate(b.pass_rate)}
                  </span>
                  <span className="text-xs text-slate-500">
                    {b.passed}/{b.total} 통과
                    {b.created_at ? ` · ${new Date(b.created_at).toLocaleString("ko-KR")}` : ""}
                  </span>
                  {b.dropped && (
                    <span className="ml-auto rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
                      점수 떨어짐
                    </span>
                  )}
                </button>
                {open === b.batch && (
                  <div className="mt-2">
                    <Report appId={appId} batch={b.batch} />
                  </div>
                )}
              </div>
            ))}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
