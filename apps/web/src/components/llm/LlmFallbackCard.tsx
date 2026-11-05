// 관리 > AI 모델 > 자동 전환 순서: 기본 연결이 안 될 때 다른 회사 연결로 넘어가는 순서와 조건.
import { CheckCircle2, FlaskConical, Save, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ChainEditor } from "@/components/llm/ChainEditor";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { toast } from "@/components/ui/toast-store";
import { useFallback, useSaveFallback, useTestFallback, type FallbackTest } from "@/lib/api/v9llm";
import { DEFAULT_TRIGGERS, chainProblem, type ChainLink, type TriggerKey } from "@/lib/llmChain";

export function TrailList({ result }: { result: FallbackTest }) {
  const tone = { failed: "red", skipped: "gray", answered: "green" } as const;
  const text = { failed: "실패", skipped: "건너뜀", answered: "답함" } as const;
  return (
    <ol className="space-y-1">
      {result.trail.map((t, i) => (
        <li key={i} className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
          <Badge tone={tone[t.status]}>{text[t.status]}</Badge>
          <span className="font-medium text-slate-800">{t.label}</span>
          <span className="text-slate-400">{t.model}</span>
          {t.error && <span className="text-slate-500">· {t.error}</span>}
        </li>
      ))}
    </ol>
  );
}

export function LlmFallbackCard({ ws, manage }: { ws: string; manage: boolean }) {
  const view = useFallback(ws);
  const save = useSaveFallback(ws);
  const test = useTestFallback(ws);
  const [enabled, setEnabled] = useState(false);
  const [links, setLinks] = useState<ChainLink[]>([]);
  const [triggers, setTriggers] = useState<Record<TriggerKey, boolean>>(DEFAULT_TRIGGERS);
  const [result, setResult] = useState<FallbackTest | null>(null);

  const data = view.data;
  useEffect(() => {
    if (!data) return;
    setEnabled(data.enabled);
    setLinks(data.links.map((l) => ({ provider_id: l.provider_id, model: l.model })));
    setTriggers({ ...DEFAULT_TRIGGERS, ...data.triggers });
  }, [data]);

  const problem = chainProblem(enabled, links, triggers);
  const dirty = useMemo(() => {
    if (!data) return false;
    return (
      enabled !== data.enabled ||
      JSON.stringify(links) !==
        JSON.stringify(data.links.map((l) => ({ provider_id: l.provider_id, model: l.model }))) ||
      JSON.stringify(triggers) !== JSON.stringify({ ...DEFAULT_TRIGGERS, ...data.triggers })
    );
  }, [data, enabled, links, triggers]);

  if (view.isLoading) return <Loading />;
  if (!data) return <ErrorBox error={view.error} />;
  const conns = data.connections;
  if (conns.length < 2 && links.length === 0) {
    return (
      <Card>
        <CardHeader
          title="자동 전환 순서"
          description="기본 연결이 안 될 때 다른 회사 연결로 넘어가요."
        />
        <CardBody>
          <p className="text-sm text-slate-500">
            AI 연결이 2개 이상일 때 쓸 수 있어요. 위에서 다른 회사의 연결을 하나 더 추가하세요.
          </p>
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title="자동 전환 순서"
        description="한 회사의 AI가 멈추거나 한도에 걸려도 일이 끊기지 않게, 정해 둔 다른 연결로 넘어가요. 빌더·AI 단계·지식 검색 모두에 적용돼요."
        action={
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              className="accent-indigo-600"
              checked={enabled}
              disabled={!manage}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            자동 전환 쓰기
          </label>
        }
      />
      <CardBody className="space-y-4">
        <ChainEditor
          idPrefix="ws-chain"
          connections={conns}
          links={links}
          triggers={triggers}
          onLinks={setLinks}
          onTriggers={setTriggers}
          readOnly={!manage}
        />
        {problem && <p className="text-xs text-amber-700">{problem}</p>}
        <ErrorBox error={save.error ?? test.error} />
        {manage && (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              disabled={!dirty || Boolean(problem) || save.isPending}
              onClick={() =>
                save.mutate(
                  { enabled, links, triggers },
                  { onSuccess: () => toast.success("자동 전환 설정을 저장했어요.") },
                )
              }
            >
              <Save className="h-4 w-4" /> {save.isPending ? "저장하는 중…" : "저장"}
            </Button>
            <Button
              variant="outline"
              disabled={dirty || !data.enabled || test.isPending}
              title={dirty ? "먼저 저장한 뒤 시험하세요." : undefined}
              onClick={() =>
                test.mutate(undefined, {
                  onSuccess: (r) => setResult(r),
                })
              }
            >
              <FlaskConical className="h-4 w-4" /> {test.isPending ? "시험하는 중…" : "시험"}
            </Button>
            <span className="text-xs text-slate-500">
              시험은 기본 연결이 실패한 것처럼 만들어(실제로 부르지 않아요) 어느 연결이 대신
              답하는지 보여 줘요.
            </span>
          </div>
        )}
        {result && (
          <div
            role="status"
            className={
              result.ok
                ? "space-y-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
                : "space-y-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700"
            }
          >
            <p className="flex items-center gap-1.5 font-medium">
              {result.ok ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
              {result.message}
              {result.answered_by && (
                <span className="font-normal opacity-80">({result.answered_by.model})</span>
              )}
            </p>
            {result.hint && <p className="text-xs opacity-80">{result.hint}</p>}
            <TrailList result={result} />
          </div>
        )}
      </CardBody>
    </Card>
  );
}
