// sections.tsx에서 분리한 구간: LlmSection
import { CheckCircle2, Bot, PlugZap, Trash2, XCircle } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { Field, Input, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import {
  baseUrlToSend,
  FALLBACK_PRESETS,
  groupPresetsWithPopular,
  presetName,
} from "@/lib/llmPresets";
import { useUpdateWorkspace, useWorkspaceInfo } from "@/lib/api/v2";
import {
  useCreateLlmProvider,
  useDeleteLlmProvider,
  useEnableDemoAi,
  useLlmProviders,
  useTestNewLlm,
  useTestSavedLlm,
  type LlmProbe,
  type NewLlmProvider,
} from "@/lib/api/workspace";
import { LlmModelPicker } from "@/pages/workspace/LlmModelPicker";
import { LlmFallbackCard } from "@/components/llm/LlmFallbackCard";
import { LlmKeysPanel } from "@/components/llm/LlmKeysPanel";
import { asProviderV9 } from "@/lib/api/v9llm";
import { optionsFrom, useListControls } from "@/lib/useListControls";
import { useLlmPresets } from "@/lib/api/v5b";
import { ModelCatalogCard } from "@/pages/workspace/costSections";

// ---------------- AI 모델 ----------------
function DefaultModels({ ws }: { ws: string }) {
  const info = useWorkspaceInfo(ws);
  const providers = useLlmProviders(ws);
  const update = useUpdateWorkspace(ws);
  const current = info.data?.settings?.default_models ?? {};
  const [chat, setChat] = useState("");
  const [embedding, setEmbedding] = useState("");
  useEffect(() => {
    setChat(current.chat ?? "");
    setEmbedding(current.embedding ?? "");
  }, [current.chat, current.embedding]);
  const list = (providers.data ?? []).filter((p) => !asProviderV9(p).rerank);
  if (!list.length) return null;
  return (
    <Card>
      <CardHeader
        title="기본 모델"
        description="단계에서 'AI 연결'을 기본으로 둔 경우와 문서 임베딩에 쓸 연결이에요."
      />
      <CardBody className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="대화·생성" htmlFor="dm-chat">
            <Select id="dm-chat" value={chat} onChange={(e) => setChat(e.target.value)}>
              <option value="">기본 연결 따르기</option>
              {list.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label} · {p.default_model}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="문서 임베딩" htmlFor="dm-emb" hint="OpenAI 계열만 임베딩을 만들 수 있어요.">
            <Select id="dm-emb" value={embedding} onChange={(e) => setEmbedding(e.target.value)}>
              <option value="">자동(OpenAI 연결)</option>
              {list
                .filter((p) => ["openai", "openai-compatible", "azure"].includes(p.provider))
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
            </Select>
          </Field>
        </div>
        <ErrorBox error={update.error} />
        <Button
          size="sm"
          disabled={update.isPending}
          onClick={() =>
            update.mutate(
              {
                settings: {
                  ...(info.data?.settings ?? {}),
                  default_models: { chat: chat || null, embedding: embedding || null },
                },
              },
              { onSuccess: () => toast.success("기본 모델을 저장했어요.") },
            )
          }
        >
          저장
        </Button>
      </CardBody>
    </Card>
  );
}

function ProbeLine({ r }: { r: LlmProbe }) {
  return (
    <span
      className={r.ok ? "basis-full text-xs text-emerald-700" : "basis-full text-xs text-red-600"}
    >
      {r.ok ? "✓ " : "✕ "}
      {r.message} {r.hint}
    </span>
  );
}

export function LlmSection({
  ws,
  manage,
  showDefaults = false,
}: {
  ws: string;
  manage: boolean;
  showDefaults?: boolean;
}) {
  const list = useLlmProviders(ws);
  const enableDemo = useEnableDemoAi(ws);
  const onlyDemo =
    (list.data?.length ?? 0) > 0 && (list.data ?? []).every((p) => p.provider === "demo");
  const pc = useListControls(list.data, {
    key: "llm-providers",
    search: (p) => `${p.label} ${p.provider} ${p.default_model ?? ""}`,
    filters: [
      {
        id: "provider",
        label: "AI 서비스",
        options: optionsFrom(list.data, (p) => p.provider),
        match: (p, v) => p.provider === v,
      },
    ],
  });
  const presetQuery = useLlmPresets();
  const presets = presetQuery.data?.length ? presetQuery.data : FALLBACK_PRESETS;
  const create = useCreateLlmProvider(ws);
  const del = useDeleteLlmProvider(ws);
  const [form, setForm] = useState<NewLlmProvider>({
    provider: "anthropic",
    label: "Claude",
    api_key: "",
    base_url: "",
    default_model: "claude-sonnet-5-5",
    is_default: true,
  });
  const chosen = presets.find((p) => p.key === form.provider);
  const testNew = useTestNewLlm(ws);
  const testSaved = useTestSavedLlm(ws);
  const [probe, setProbe] = useState<LlmProbe | null>(null);
  const [rowProbe, setRowProbe] = useState<Record<string, LlmProbe>>({});
  const runTest = () =>
    testNew.mutate(
      {
        provider: form.provider,
        api_key: form.api_key,
        base_url: baseUrlToSend(chosen, form.base_url ?? ""),
        model: form.default_model,
      },
      {
        onSuccess: (r) => {
          setProbe(r);
          // 지금 고른 모델이 목록에 없으면 첫 모델로 맞춘다
          if (r.ok && r.models.length && !r.models.some((m) => m.model === form.default_model)) {
            const preferred = r.models.find((m) =>
              (chosen?.models ?? []).some((p) => p.model === m.model),
            );
            const pick = preferred ?? r.models[0];
            if (pick) setForm((f) => ({ ...f, default_model: pick.model }));
          }
        },
        onError: (err) => toast.error(err),
      },
    );

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { ...form, base_url: baseUrlToSend(chosen, form.base_url ?? "") },
      {
        onSuccess: () => {
          toast.success("AI 연결을 저장했어요. 키는 암호화되어 다시 볼 수 없어요.");
          setForm({ ...form, api_key: "" });
        },
      },
    );
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <Card className="min-w-0">
          <CardHeader title="AI 연결" description="빌더와 AI 단계가 이 키로 모델을 불러요." />
          <CardBody className="p-0">
            {list.isLoading && <Loading />}
            <ErrorBox error={list.error} />
            {list.data?.length === 0 && (
              <EmptyState
                compact
                icon={<Bot className="h-5 w-5" />}
                title="아직 AI 연결이 없어요"
                description={
                  manage
                    ? "'새 AI 연결'에서 제공사를 고르고 키를 넣은 뒤 '연결 테스트'를 눌러요. 등록해야 빌더와 AI 단계가 동작해요."
                    : "소유자·관리자가 AI 키를 등록해야 빌더와 AI 단계가 동작해요. 관리자에게 요청하세요."
                }
                action={
                  manage
                    ? {
                        label: enableDemo.isPending ? "켜는 중…" : "키 없이 데모 AI로 체험하기",
                        onClick: () =>
                          enableDemo.mutate(undefined, {
                            onSuccess: () => toast.success("데모 AI를 켰어요. 예시 답만 나와요."),
                            onError: (err) => toast.error(err),
                          }),
                      }
                    : null
                }
              />
            )}
            {onlyDemo && (
              <p
                className="mx-4 mb-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 sm:mx-5"
                data-testid="demo-banner"
              >
                지금은 데모 AI예요. 실제 AI가 아니라 예시 답만 나와요. 키가 있는 AI 연결을 등록하면
                그 연결이 기본이 되어 진짜로 동작해요. 데모로 올린 지식베이스 문서는 키를 등록한 뒤
                &apos;다시 처리&apos;해 주세요.
              </p>
            )}
            {(list.data?.length ?? 0) > 0 && (
              <ListToolbar c={pc} placeholder="이름·모델 검색" className="px-4 pb-3 sm:px-5" />
            )}
            <ul className="divide-y divide-slate-100 border-t border-slate-100">
              {pc.pageItems.map((p) => (
                <li
                  key={p.id}
                  className="flex flex-wrap items-center gap-2 px-4 py-3 text-sm sm:px-5"
                >
                  <span className="font-medium">{p.label}</span>
                  <Badge tone="blue">{presetName(presets, p.provider)}</Badge>
                  {p.is_default && <Badge tone="green">기본</Badge>}
                  {asProviderV9(p).rerank && <Badge tone="amber">재정렬 전용</Badge>}
                  <span className="basis-full text-xs text-slate-500 sm:basis-auto">
                    {p.default_model} · 키 {p.api_key_masked}
                    {p.base_url && ` · ${p.base_url}`}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="ml-auto"
                    disabled={testSaved.isPending && testSaved.variables === p.id}
                    onClick={() =>
                      testSaved.mutate(p.id, {
                        onSuccess: (r) => setRowProbe((m) => ({ ...m, [p.id]: r })),
                        onError: (err) => toast.error(err),
                      })
                    }
                  >
                    <PlugZap className="h-3.5 w-3.5" />
                    {testSaved.isPending && testSaved.variables === p.id
                      ? "확인 중…"
                      : "연결 테스트"}
                  </Button>
                  {rowProbe[p.id] && <ProbeLine r={rowProbe[p.id] as LlmProbe} />}
                  {manage && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-red-600"
                      aria-label={`${p.label} 연결 삭제`}
                      onClick={() => {
                        if (window.confirm(`'${p.label}' 연결을 지울까요?`)) del.mutate(p.id);
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                  <LlmKeysPanel ws={ws} provider={p} manage={manage} />
                </li>
              ))}
            </ul>
            <NoMatch c={pc} />
            {(list.data?.length ?? 0) > 0 && (
              <ListPager c={pc} className="border-t border-slate-100 px-4 py-2 sm:px-5" />
            )}
          </CardBody>
        </Card>
        {manage && (
          <Card className="min-w-0">
            <CardHeader title="새 AI 연결" />
            <CardBody>
              <form onSubmit={submit} className="space-y-3">
                <Field
                  label="제공사"
                  htmlFor="llm-provider"
                  hint={chosen?.note || (chosen?.native ? undefined : "키만 넣으면 돼요.")}
                >
                  <Select
                    id="llm-provider"
                    value={form.provider}
                    onChange={(e) => {
                      const p = presets.find((x) => x.key === e.target.value);
                      setForm({
                        ...form,
                        provider: e.target.value,
                        default_model: p?.default_model ?? "",
                        label: p?.name.split(" (")[0] ?? form.label,
                        base_url: "",
                        is_default: p?.rerank ? false : true,
                      });
                      setProbe(null);
                    }}
                  >
                    {groupPresetsWithPopular(presets).map((g) => (
                      <optgroup key={g.group} label={g.group}>
                        {g.items.map((p) => (
                          <option key={p.key} value={p.key}>
                            {p.name}
                            {p.vision ? " · 이미지" : ""}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </Select>
                </Field>
                <Field label="이름" htmlFor="llm-label">
                  <Input
                    id="llm-label"
                    required
                    value={form.label}
                    onChange={(e) => setForm({ ...form, label: e.target.value })}
                  />
                </Field>
                <Field label="API 키" htmlFor="llm-key">
                  <Input
                    id="llm-key"
                    type="password"
                    autoComplete="off"
                    required
                    value={form.api_key}
                    onChange={(e) => {
                      setForm({ ...form, api_key: e.target.value });
                      setProbe(null);
                    }}
                  />
                </Field>
                <Field
                  label="기본 모델"
                  htmlFor="llm-model"
                  hint={
                    chosen?.models.length
                      ? "대표 모델이에요. '연결 테스트'를 누르면 이 키로 쓸 수 있는 모델을 모두 불러와요."
                      : "'연결 테스트'로 모델 목록을 불러오거나 이름을 직접 적어요."
                  }
                >
                  <LlmModelPicker
                    id="llm-model"
                    value={form.default_model}
                    onChange={(v) => setForm({ ...form, default_model: v })}
                    presetModels={chosen?.models ?? []}
                    fetched={probe?.ok ? probe.models : null}
                  />
                </Field>
                {chosen?.needs_base_url ? (
                  <Field
                    label={form.provider === "azure" ? "Azure 리소스 주소" : "주소(base URL)"}
                    htmlFor="llm-base"
                    hint={
                      form.provider === "azure"
                        ? "예: https://my-resource.openai.azure.com/ · 기본 모델 칸에는 배포 이름을 적어요."
                        : undefined
                    }
                  >
                    <Input
                      id="llm-base"
                      required
                      placeholder={
                        form.provider === "azure"
                          ? "https://my-resource.openai.azure.com/"
                          : "https://example.com/v1"
                      }
                      value={form.base_url}
                      onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                    />
                  </Field>
                ) : (
                  chosen?.base_url && (
                    <details className="text-sm">
                      <summary className="cursor-pointer text-xs text-slate-500">
                        주소 바꾸기(고급) · 기본 {chosen.base_url}
                      </summary>
                      <div className="mt-2">
                        <Field label="주소(base URL)" htmlFor="llm-base">
                          <Input
                            id="llm-base"
                            placeholder={chosen.base_url}
                            value={form.base_url}
                            onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                          />
                        </Field>
                      </div>
                    </details>
                  )
                )}
                {!chosen?.rerank && (
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={form.is_default}
                      onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
                    />
                    기본 연결로 쓰기
                  </label>
                )}
                {probe && (
                  <div
                    role="status"
                    className={
                      probe.ok
                        ? "flex gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
                        : "flex gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700"
                    }
                  >
                    {probe.ok ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                    ) : (
                      <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    )}
                    <span>
                      {probe.message}
                      {probe.hint && <span className="block text-xs opacity-80">{probe.hint}</span>}
                    </span>
                  </div>
                )}
                <ErrorBox error={create.error} />
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={!form.api_key.trim() || testNew.isPending}
                    onClick={runTest}
                  >
                    <PlugZap className="h-4 w-4" />
                    {testNew.isPending ? "확인 중…" : "연결 테스트"}
                  </Button>
                  <Button type="submit" disabled={create.isPending}>
                    저장
                  </Button>
                </div>
              </form>
            </CardBody>
          </Card>
        )}
      </div>
      {showDefaults && manage && <DefaultModels ws={ws} />}
      {showDefaults && <LlmFallbackCard ws={ws} manage={manage} />}
      <ModelCatalogCard />
    </div>
  );
}
