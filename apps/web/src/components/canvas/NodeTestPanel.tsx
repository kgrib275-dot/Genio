// 캔버스 설정 패널의 '이 단계만 시험': 앞 단계 값을 채워 놓고 이 단계 하나만 실행해 본다.
import { CheckCircle2, FlaskConical, Loader2, XCircle } from "lucide-react";
import { useState } from "react";
import { ValueRows } from "@/components/run/ValueInspector";
import { Button } from "@/components/ui/button";
import {
  parseTestValue,
  testValueText,
  useNodeTestInputs,
  useRunNodeTest,
  type NodeTestInputs,
  type NodeTestResult,
} from "@/lib/api/nodeTest";
import type { GraphNode } from "@/lib/api/types";
import { flattenValue } from "@/lib/valueFlatten";

type Draft = Record<string, Record<string, string>>;

function toDraft(inputs: NodeTestInputs): Draft {
  const d: Draft = {};
  for (const g of inputs.groups) {
    d[g.scope] = Object.fromEntries(g.fields.map((f) => [f.field, testValueText(f.value)]));
  }
  return d;
}

export function NodeTestPanel({ appId, node }: { appId: string; node: GraphNode }) {
  const [open, setOpen] = useState(false);
  const [inputs, setInputs] = useState<NodeTestInputs | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [result, setResult] = useState<NodeTestResult | null>(null);
  const load = useNodeTestInputs(appId);
  const run = useRunNodeTest(appId);

  const fill = () => {
    setResult(null);
    load.mutate(
      { nodeId: node.id, data: node.data },
      {
        onSuccess: (r) => {
          setInputs(r);
          setDraft(toDraft(r));
        },
      },
    );
  };

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && !inputs) fill();
  };

  const submit = () => {
    if (!inputs) return;
    if (inputs.risky && !window.confirm(`${inputs.warn ?? ""}\n그래도 이 단계만 실행할까요?`))
      return;
    const values: Record<string, Record<string, unknown>> = {};
    for (const g of inputs.groups) {
      values[g.scope] = Object.fromEntries(
        g.fields.map((f) => [f.field, parseTestValue(draft[g.scope]?.[f.field] ?? "", f.kind)]),
      );
    }
    run.mutate({ nodeId: node.id, data: node.data, values }, { onSuccess: setResult });
  };

  return (
    <section className="mt-4 rounded-lg border border-slate-200" data-testid="node-test">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-xs font-medium text-slate-700 hover:bg-slate-50"
      >
        <FlaskConical className="h-3.5 w-3.5 text-indigo-500" /> 이 단계만 시험
        <span className="ml-auto text-slate-400">{open ? "접기" : "펼치기"}</span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-slate-100 px-3 py-2 text-xs">
          {load.isPending && (
            <p className="flex items-center gap-1 text-slate-500">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> 값을 채우는 중…
            </p>
          )}
          {load.error && (
            <p className="text-red-700">
              값을 불러오지 못했어요. 흐름을 먼저 저장한 뒤 다시 열어 보세요.
            </p>
          )}
          {inputs && !inputs.testable && (
            <p className="rounded bg-amber-50 px-2 py-1.5 text-amber-900">
              {inputs.reason ?? "이 단계는 단독으로 시험할 수 없어요."} 흐름 전체를 테스트 실행해서
              확인하세요.
            </p>
          )}
          {inputs?.testable && (
            <>
              <p className="text-slate-500">
                {inputs.last_run_id
                  ? "마지막으로 성공한 실행의 값으로 채웠어요. 고쳐서 시험해도 돼요."
                  : "아직 성공한 실행이 없어 값이 비어 있어요. 아래에 값을 직접 적어 주세요."}
              </p>
              {inputs.groups.length === 0 && (
                <p className="text-slate-500">
                  이 단계는 앞 단계 값을 쓰지 않아요. 바로 시험해 보세요.
                </p>
              )}
              {inputs.groups.map((g) => (
                <fieldset key={g.scope} className="space-y-1">
                  <legend className="font-medium text-slate-700">{g.label}</legend>
                  {g.fields.map((f) => (
                    <label key={f.field} className="block">
                      <span className="text-slate-500">
                        {f.field}
                        {!f.from_last_run && <span className="ml-1 text-amber-700">(값 없음)</span>}
                      </span>
                      <input
                        type="text"
                        value={draft[g.scope]?.[f.field] ?? ""}
                        onChange={(e) =>
                          setDraft((d) => ({
                            ...d,
                            [g.scope]: { ...d[g.scope], [f.field]: e.target.value },
                          }))
                        }
                        className="mt-0.5 h-8 w-full rounded-lg border border-slate-300 bg-white px-2 text-xs focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/15"
                      />
                    </label>
                  ))}
                </fieldset>
              ))}
              {inputs.warn && (
                <p className={inputs.risky ? "text-amber-800" : "text-slate-500"}>{inputs.warn}</p>
              )}
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={submit} disabled={run.isPending}>
                  {run.isPending ? "시험하는 중…" : "시험하기"}
                </Button>
                <Button size="sm" variant="ghost" onClick={fill} disabled={load.isPending}>
                  값 다시 채우기
                </Button>
              </div>
            </>
          )}
          {run.error && <p className="text-red-700">시험하지 못했어요. 잠시 뒤 다시 해 보세요.</p>}
          {result && (
            <div
              role="status"
              className={
                result.ok
                  ? "rounded-lg border border-emerald-200 bg-emerald-50/60"
                  : "rounded-lg border border-red-200 bg-red-50/60"
              }
            >
              <p
                className={
                  result.ok
                    ? "flex items-center gap-1 px-2 py-1.5 font-medium text-emerald-800"
                    : "flex items-center gap-1 px-2 py-1.5 font-medium text-red-800"
                }
              >
                {result.ok ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : (
                  <XCircle className="h-3.5 w-3.5" />
                )}
                {result.ok ? "잘 실행됐어요" : "실행하지 못했어요"}
                <span className="ml-auto font-normal text-slate-500">
                  {result.ms}ms
                  {result.tokens.input_tokens + result.tokens.output_tokens > 0 &&
                    ` · 토큰 ${result.tokens.input_tokens}/${result.tokens.output_tokens}`}
                </span>
              </p>
              {result.ok ? (
                <>
                  {result.summary && (
                    <p className="whitespace-pre-wrap px-2 pb-1 text-slate-700">{result.summary}</p>
                  )}
                  {result.handle && (
                    <p className="px-2 pb-1 text-slate-600">고른 길: {result.handle}</p>
                  )}
                  <ValueRows nodeId={node.id} rows={flattenValue(result.output)} />
                </>
              ) : (
                <div className="px-2 pb-2 text-red-800">
                  <p>{result.error?.message}</p>
                  <p>{result.error?.hint}</p>
                </div>
              )}
              {result.logs.length > 0 && (
                <p className="whitespace-pre-wrap border-t border-slate-100 px-2 py-1 text-slate-500">
                  {result.logs.join("\n")}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
