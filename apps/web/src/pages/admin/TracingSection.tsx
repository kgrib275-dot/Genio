// 외부 추적(v0.6): 끝난 실행을 Langfuse·LangSmith로 보내 단계·AI 사용량을 살펴본다(소유자·관리자)
import { Activity, PlugZap } from "lucide-react";
import { useEffect, useState } from "react";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { useSaveTracing, useTestTracing, useTracing, type TracingConfig } from "@/lib/api/v6mcp";

type Target = "langfuse" | "langsmith";

function Toggle({
  id,
  checked,
  onChange,
  label,
}: {
  id: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label htmlFor={id} className="inline-flex cursor-pointer items-center gap-2 text-sm">
      <input
        id={id}
        type="checkbox"
        className="h-4 w-4 accent-indigo-600"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  );
}

export function TracingSection({ ws }: { ws: string }) {
  const cfg = useTracing(ws);
  const save = useSaveTracing(ws);
  const test = useTestTracing(ws);
  const [lf, setLf] = useState({ enabled: false, host: "", public_key: "", secret_key: "" });
  const [ls, setLs] = useState({ enabled: false, endpoint: "", project: "", api_key: "" });
  const [result, setResult] = useState<Partial<Record<Target, { ok: boolean; message: string }>>>(
    {},
  );

  useEffect(() => {
    const d: TracingConfig | undefined = cfg.data;
    if (!d) return;
    setLf({
      enabled: d.langfuse.enabled,
      host: d.langfuse.host,
      public_key: d.langfuse.public_key,
      secret_key: "",
    });
    setLs({
      enabled: d.langsmith.enabled,
      endpoint: d.langsmith.endpoint,
      project: d.langsmith.project,
      api_key: "",
    });
  }, [cfg.data]);

  const submit = () =>
    save.mutate(
      {
        langfuse: {
          enabled: lf.enabled,
          host: lf.host,
          public_key: lf.public_key,
          ...(lf.secret_key ? { secret_key: lf.secret_key } : {}),
        },
        langsmith: {
          enabled: ls.enabled,
          endpoint: ls.endpoint,
          project: ls.project,
          ...(ls.api_key ? { api_key: ls.api_key } : {}),
        },
      },
      { onSuccess: () => toast.success("저장했어요. 이제 끝난 실행부터 보내요.") },
    );

  const runTest = (t: Target) =>
    test.mutate(t, {
      onSuccess: (r) => setResult((cur) => ({ ...cur, [t]: r })),
    });

  if (cfg.isLoading) return <Loading />;
  return (
    <div className="space-y-4">
      <Card>
        <CardBody className="flex gap-3 text-sm text-slate-600">
          <Activity className="mt-0.5 h-5 w-5 shrink-0 text-indigo-500" />
          <p>
            실행이 끝날 때마다 단계별 기록(걸린 시간, AI 모델·토큰·비용)을 외부 추적 서비스로
            보내요. 보낸 값에는 입력과 결과가 들어가니, 회사 정책에 맞는 곳에만 연결하세요. 보내기에
            실패해도 실행에는 영향이 없어요.
          </p>
        </CardBody>
      </Card>
      <ErrorBox error={cfg.error ?? save.error ?? test.error} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Langfuse" description="클라우드 또는 직접 설치한 Langfuse" />
          <CardBody className="space-y-3">
            <Toggle
              id="lf-on"
              label="Langfuse로 보내기"
              checked={lf.enabled}
              onChange={(v) => setLf({ ...lf, enabled: v })}
            />
            <Field label="주소" htmlFor="lf-host" hint="예: https://cloud.langfuse.com">
              <Input
                id="lf-host"
                value={lf.host}
                onChange={(e) => setLf({ ...lf, host: e.target.value })}
              />
            </Field>
            <Field label="공개 키(pk-lf-…)" htmlFor="lf-pk">
              <Input
                id="lf-pk"
                value={lf.public_key}
                onChange={(e) => setLf({ ...lf, public_key: e.target.value })}
              />
            </Field>
            <Field
              label="비밀 키(sk-lf-…)"
              htmlFor="lf-sk"
              hint={
                cfg.data?.langfuse.has_secret
                  ? `저장됨 ${cfg.data.langfuse.secret_key}. 바꿀 때만 새로 넣으세요.`
                  : "암호화해서 저장하고 다시 보여 주지 않아요."
              }
            >
              <Input
                id="lf-sk"
                type="password"
                autoComplete="off"
                value={lf.secret_key}
                onChange={(e) => setLf({ ...lf, secret_key: e.target.value })}
              />
            </Field>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => runTest("langfuse")}
                disabled={test.isPending}
              >
                <PlugZap className="h-4 w-4" /> 연결 시험
              </Button>
              {result.langfuse && (
                <span
                  className={
                    result.langfuse.ok ? "text-xs text-emerald-700" : "text-xs text-red-600"
                  }
                >
                  {result.langfuse.message}
                </span>
              )}
            </div>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="LangSmith" description="LangChain의 추적 서비스" />
          <CardBody className="space-y-3">
            <Toggle
              id="ls-on"
              label="LangSmith로 보내기"
              checked={ls.enabled}
              onChange={(v) => setLs({ ...ls, enabled: v })}
            />
            <Field label="주소" htmlFor="ls-endpoint" hint="예: https://api.smith.langchain.com">
              <Input
                id="ls-endpoint"
                value={ls.endpoint}
                onChange={(e) => setLs({ ...ls, endpoint: e.target.value })}
              />
            </Field>
            <Field label="프로젝트 이름" htmlFor="ls-project">
              <Input
                id="ls-project"
                value={ls.project}
                onChange={(e) => setLs({ ...ls, project: e.target.value })}
              />
            </Field>
            <Field
              label="API 키"
              htmlFor="ls-key"
              hint={
                cfg.data?.langsmith.has_key
                  ? `저장됨 ${cfg.data.langsmith.api_key}. 바꿀 때만 새로 넣으세요.`
                  : "암호화해서 저장하고 다시 보여 주지 않아요."
              }
            >
              <Input
                id="ls-key"
                type="password"
                autoComplete="off"
                value={ls.api_key}
                onChange={(e) => setLs({ ...ls, api_key: e.target.value })}
              />
            </Field>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => runTest("langsmith")}
                disabled={test.isPending}
              >
                <PlugZap className="h-4 w-4" /> 연결 시험
              </Button>
              {result.langsmith && (
                <span
                  className={
                    result.langsmith.ok ? "text-xs text-emerald-700" : "text-xs text-red-600"
                  }
                >
                  {result.langsmith.message}
                </span>
              )}
            </div>
          </CardBody>
        </Card>
      </div>
      <div>
        <Button onClick={submit} disabled={save.isPending}>
          {save.isPending ? "저장하는 중…" : "저장"}
        </Button>
        <p className="mt-2 text-xs text-slate-500">
          연결 시험은 저장된 키로 해요. 키를 바꿨다면 먼저 저장하세요.
        </p>
      </div>
    </div>
  );
}
