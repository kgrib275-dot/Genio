import { Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { ko } from "@/i18n/ko";
import { useApp } from "@/lib/api/apps";
import { useApiKeys, useDeleteApiKey } from "@/lib/api/v2";
import {
  KEY_SCOPE_LABELS,
  useCreateApiKeyScoped,
  type KeyScope,
  type NewApiKeyV5,
} from "@/lib/api/v5b";
import { copyText, formatDate } from "@/lib/cn";
import { useListControls } from "@/lib/useListControls";
import { AppNav } from "@/pages/apps/AppNav";
import { McpSection } from "@/pages/apps/McpSection";
import { EmptyState } from "@/components/EmptyState";

function CodeBlock({ code }: { code: string }) {
  return (
    <div className="group relative">
      <pre className="overflow-x-auto rounded-xl bg-slate-900 px-4 py-3 font-mono text-[12px] leading-relaxed text-slate-100">
        {code}
      </pre>
      <button
        type="button"
        aria-label="복사"
        className="absolute right-2 top-2 rounded-md bg-white/10 p-1.5 text-slate-200 opacity-80 hover:bg-white/20 group-hover:opacity-100"
        onClick={async () => {
          if (await copyText(code)) toast.success(ko.common.copied);
        }}
      >
        <Copy className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

export default function AppApiPage() {
  const { id: appId = "" } = useParams();
  const app = useApp(appId);
  const keys = useApiKeys(appId);
  const kc = useListControls(keys.data, {
    key: "app-api-keys",
    defaultSize: 10,
    search: (k) => `${k.name} ${k.prefix}`,
    filters: [
      {
        id: "used",
        label: "사용",
        options: [
          { value: "used", label: "쓴 적 있음" },
          { value: "unused", label: "쓴 적 없음" },
        ],
        match: (k, v) => (v === "used" ? Boolean(k.last_used_at) : !k.last_used_at),
      },
    ],
  });
  const create = useCreateApiKeyScoped(appId);
  const [scopes, setScopes] = useState<KeyScope[]>(["chat", "run"]);
  const del = useDeleteApiKey(appId);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<NewApiKeyV5 | null>(null);
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const base = `${origin}/api/v1/service`;
  const key = "gk-여기에_키";

  return (
    <div className="flex min-h-full flex-col">
      <AppNav appId={appId} title={app.data?.name ?? ""} icon={app.data?.icon} help="api" />
      <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6">
        <Card>
          <CardHeader
            title="API 키"
            description="다른 프로그램에서 이 앱을 부를 때 써요. 키는 만들 때 한 번만 보여요."
          />
          <CardBody className="space-y-4">
            <form
              className="flex flex-col gap-2 sm:flex-row sm:flex-wrap"
              onSubmit={(e) => {
                e.preventDefault();
                if (scopes.length === 0) {
                  toast.error("권한을 하나 이상 고르세요.");
                  return;
                }
                create.mutate(
                  { name: name.trim() || "기본 키", scopes },
                  {
                    onSuccess: (k) => {
                      setCreated(k);
                      setName("");
                    },
                    onError: (err) => toast.error(err),
                  },
                );
              }}
            >
              <Input
                aria-label="키 이름"
                placeholder="키 이름(예: 사내 홈페이지)"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <Button type="submit" disabled={create.isPending}>
                <Plus className="h-4 w-4" /> 키 만들기
              </Button>
              <fieldset className="flex basis-full flex-wrap items-center gap-3 text-sm">
                <legend className="sr-only">이 키로 할 수 있는 일</legend>
                <span className="text-xs text-slate-500">할 수 있는 일:</span>
                {(Object.keys(KEY_SCOPE_LABELS) as KeyScope[]).map((sc) => (
                  <label key={sc} className="inline-flex cursor-pointer items-center gap-1.5">
                    <input
                      type="checkbox"
                      className="accent-indigo-600"
                      checked={scopes.includes(sc)}
                      onChange={(e) =>
                        setScopes((cur) =>
                          e.target.checked ? [...cur, sc] : cur.filter((x) => x !== sc),
                        )
                      }
                    />
                    {KEY_SCOPE_LABELS[sc]}
                  </label>
                ))}
              </fieldset>
            </form>
            {keys.isLoading && <Loading />}
            <ErrorBox error={keys.error} />
            {keys.data?.length === 0 && (
              <EmptyState
                compact
                icon={<KeyRound className="h-5 w-5" />}
                title="아직 만든 키가 없어요"
                description="위에서 이름과 권한 범위를 고르고 '키 만들기'를 누르면, 다른 시스템에서 이 앱을 부를 수 있어요."
              />
            )}
            {(keys.data?.length ?? 0) > 0 && <ListToolbar c={kc} placeholder="키 이름으로 찾기" />}
            <NoMatch c={kc} />
            <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 empty:hidden">
              {kc.pageItems.map((k) => (
                <li key={k.id} className="flex flex-wrap items-center gap-2 px-4 py-3 text-sm">
                  <KeyRound className="h-4 w-4 text-slate-400" />
                  <span className="font-medium">{k.name}</span>
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                    {k.prefix}…
                  </code>
                  {((k as { scopes?: KeyScope[] }).scopes ?? ["chat", "run"]).map((sc) => (
                    <span
                      key={sc}
                      className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] text-indigo-700"
                    >
                      {KEY_SCOPE_LABELS[sc] ?? sc}
                    </span>
                  ))}
                  <span className="text-xs text-slate-400">
                    만든 날 {formatDate(k.created_at)} · 마지막 사용{" "}
                    {k.last_used_at ? formatDate(k.last_used_at) : "없음"}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="ml-auto text-red-600"
                    aria-label={`${k.name} 키 지우기`}
                    onClick={() => {
                      if (
                        window.confirm(
                          `'${k.name}' 키를 지울까요? 이 키를 쓰던 프로그램은 바로 막혀요.`,
                        )
                      )
                        del.mutate(k.id, { onError: (err) => toast.error(err) });
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </li>
              ))}
            </ul>
            {(keys.data?.length ?? 0) > 0 && <ListPager c={kc} />}
          </CardBody>
        </Card>

        <McpSection appId={appId} />

        <Card>
          <CardHeader
            title="사용 방법"
            description="요청 헤더에 Authorization: Bearer 키 를 붙여요. 키는 서버에만 두세요."
          />
          <CardBody className="space-y-4 text-sm">
            <div className="space-y-1.5">
              <p className="font-medium text-slate-700">챗봇에 질문하기</p>
              <CodeBlock
                code={`curl -X POST ${base}/chat-messages \\
  -H "Authorization: Bearer ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{"query": "연차는 며칠인가요?", "user": "user-1"}'`}
              />
              <p className="text-xs text-slate-500">
                응답의 <code>conversation_id</code>를 다음 요청에 넣으면 대화가 이어져요.
              </p>
            </div>
            <div className="space-y-1.5">
              <p className="font-medium text-slate-700">흐름 실행하기</p>
              <CodeBlock
                code={`curl -X POST ${base}/workflows/run \\
  -H "Authorization: Bearer ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{"inputs": {"message": "결제가 두 번 됐어요"}}'`}
              />
            </div>
            <div className="space-y-1.5">
              <p className="font-medium text-slate-700">실행 기록 읽기('기록 읽기' 권한)</p>
              <CodeBlock
                code={`curl ${base}/runs?limit=20 \\\n  -H "Authorization: Bearer ${key}"`}
              />
            </div>
            <div className="space-y-1.5">
              <p className="font-medium text-slate-700">입력 항목 알아보기</p>
              <CodeBlock code={`curl ${base}/parameters \\\n  -H "Authorization: Bearer ${key}"`} />
            </div>
          </CardBody>
        </Card>
      </div>

      <Dialog
        open={Boolean(created)}
        onClose={() => setCreated(null)}
        title="새 API 키"
        footer={<Button onClick={() => setCreated(null)}>확인했어요</Button>}
      >
        <div className="space-y-3 text-sm">
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-amber-900">
            이 키는 지금 한 번만 보여요. 복사해서 안전한 곳에 두세요.
          </p>
          <Field label={created?.name ?? "키"}>
            <div className="flex gap-2">
              <Input
                readOnly
                aria-label="API 키"
                value={created?.key ?? ""}
                className="font-mono text-xs"
              />
              <Button
                variant="outline"
                onClick={async () => {
                  if (created && (await copyText(created.key))) toast.success(ko.common.copied);
                }}
              >
                <Copy className="h-4 w-4" /> 복사
              </Button>
            </div>
          </Field>
        </div>
      </Dialog>
    </div>
  );
}
