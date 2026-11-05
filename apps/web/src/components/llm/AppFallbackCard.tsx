// 앱 기능 > AI 자동 전환: 이 앱만 워크스페이스 설정과 다르게 쓰고 싶을 때.
import { useEffect, useState } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { ChainEditor } from "@/components/llm/ChainEditor";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { toast } from "@/components/ui/toast-store";
import {
  appFallbackOf,
  useFallback,
  useSaveAppFallback,
  type AppFallback,
  type FallbackMode,
} from "@/lib/api/v9llm";
import { chainProblem } from "@/lib/llmChain";

const MODES: { value: FallbackMode; label: string; hint: string }[] = [
  {
    value: "inherit",
    label: "워크스페이스 설정 따르기",
    hint: "관리 > AI 모델의 자동 전환 순서를 그대로 써요.",
  },
  { value: "off", label: "이 앱은 쓰지 않기", hint: "AI가 안 되면 넘어가지 않고 오류로 알려요." },
  {
    value: "custom",
    label: "이 앱만의 순서",
    hint: "아래에서 이 앱의 대체 연결과 조건을 따로 정해요.",
  },
];

export function AppFallbackCard({
  appId,
  wsId,
  features,
  readOnly,
}: {
  appId: string;
  wsId: string;
  features: unknown;
  readOnly: boolean;
}) {
  const saved = appFallbackOf(features);
  const [draft, setDraft] = useState<AppFallback>(saved);
  const conns = useFallback(wsId);
  const save = useSaveAppFallback(appId);
  const key = JSON.stringify(saved);
  useEffect(() => setDraft(appFallbackOf(features)), [key]); // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = JSON.stringify(draft) !== key;
  const problem = chainProblem(draft.mode === "custom", draft.links, draft.triggers);

  return (
    <Card>
      <CardHeader
        title="AI 자동 전환"
        description="AI 서비스가 멈추거나 한도에 걸렸을 때 다른 회사 연결로 넘어갈지 정해요."
        action={
          !readOnly && (
            <Button
              size="sm"
              disabled={!dirty || Boolean(problem) || save.isPending}
              onClick={() =>
                save.mutate(draft, { onSuccess: () => toast.success("AI 자동 전환을 저장했어요.") })
              }
            >
              저장
            </Button>
          )
        }
      />
      <CardBody className="space-y-3">
        <div role="radiogroup" aria-label="AI 자동 전환 방식" className="space-y-1.5">
          {MODES.map((m) => (
            <label key={m.value} className="flex items-start gap-2 text-sm text-slate-700">
              <input
                type="radio"
                name={`fb-mode-${appId}`}
                className="mt-0.5 accent-indigo-600"
                checked={draft.mode === m.value}
                disabled={readOnly}
                onChange={() => setDraft({ ...draft, mode: m.value })}
              />
              <span>
                {m.label}
                <span className="ml-1.5 text-xs text-slate-400">{m.hint}</span>
              </span>
            </label>
          ))}
        </div>
        {draft.mode === "custom" && (
          <div className="rounded-lg border border-slate-200 p-3">
            <ChainEditor
              idPrefix="app-chain"
              connections={conns.data?.connections ?? []}
              links={draft.links}
              triggers={draft.triggers}
              onLinks={(links) => setDraft({ ...draft, links })}
              onTriggers={(triggers) => setDraft({ ...draft, triggers })}
              readOnly={readOnly}
            />
          </div>
        )}
        {problem && <p className="text-xs text-amber-700">{problem}</p>}
        <ErrorBox error={save.error ?? conns.error} />
      </CardBody>
    </Card>
  );
}
