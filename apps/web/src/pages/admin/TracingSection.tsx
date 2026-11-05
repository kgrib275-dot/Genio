// 외부 추적(v0.6 → v0.9 확대): 끝난 실행을 여러 추적 서비스로 보내 단계·AI 사용량을 살펴본다(소유자·관리자)
import { Activity, Plus, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ProviderCard } from "@/components/tracing/ProviderCard";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { toast } from "@/components/ui/toast-store";
import {
  useSaveTraceConfig,
  useTestTrace,
  useTraceConfig,
  type TraceConfig,
} from "@/lib/api/trace";
import {
  kindOf,
  MAX_PROVIDERS,
  newDraft,
  toDraft,
  toPayload,
  type ProviderDraft,
} from "@/lib/tracingForm";

export function TracingSection({ ws }: { ws: string }) {
  const cfg = useTraceConfig(ws);
  const save = useSaveTraceConfig(ws);
  const test = useTestTrace(ws);
  const [drafts, setDrafts] = useState<ProviderDraft[]>([]);
  const [includeContent, setIncludeContent] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const loaded = useRef(false);

  const load = (d: TraceConfig) => {
    setDrafts(d.providers.map(toDraft));
    setIncludeContent(d.include_content);
  };
  // 처음 한 번만 서버 값으로 채운다(시험 뒤 다시 읽어도 편집 중인 값은 지키려고)
  useEffect(() => {
    if (cfg.data && !loaded.current) {
      loaded.current = true;
      load(cfg.data);
    }
  }, [cfg.data]);

  if (cfg.isLoading) return <Loading />;
  const data = cfg.data;
  const savedById = new Map((data?.providers ?? []).map((p) => [p.id, p]));
  const kinds = data?.kinds ?? [];

  const submit = () =>
    save.mutate(
      { include_content: includeContent, providers: drafts.map(toPayload) },
      {
        onSuccess: (d) => {
          load(d);
          toast.success("저장했어요. 이제 끝난 실행부터 보내요.");
        },
      },
    );

  const update = (uid: string, next: ProviderDraft) =>
    setDrafts((cur) => cur.map((d) => (d.uid === uid ? next : d)));

  return (
    <div className="space-y-4">
      <Card>
        <CardBody className="flex gap-3 text-sm text-slate-600">
          <Activity className="mt-0.5 h-5 w-5 shrink-0 text-indigo-500" />
          <p>
            실행이 끝날 때마다 단계별 기록(걸린 시간, AI 모델·토큰·비용)을 외부 추적 서비스로
            보내요. 서비스는 여러 개를 함께 연결할 수 있고, 서비스마다 켜고 끄거나 일부만 골라 보낼
            수 있어요. 보내기에 실패해도 실행에는 영향이 없어요.
          </p>
        </CardBody>
      </Card>

      <Card>
        <CardBody className="space-y-2">
          <label htmlFor="trace-content" className="flex cursor-pointer items-start gap-2 text-sm">
            <input
              id="trace-content"
              type="checkbox"
              className="mt-0.5 h-4 w-4 accent-indigo-600"
              checked={includeContent}
              onChange={(e) => setIncludeContent(e.target.checked)}
            />
            <span>
              <span className="font-medium text-slate-900">입력·출력 내용도 함께 보내기</span>
              <span className="block text-xs text-slate-500">
                꺼 두면(권장) 단계 이름·상태·시간·토큰·비용만 보내고, 사용자가 입력한 글과 AI의 답은
                보내지 않아요. 켜면 내용을 2KB까지 잘라 보내고, 앱의 비밀 환경 값은 가려요. 회사
                정책에 맞는 곳에만 켜세요.
              </span>
            </span>
          </label>
          {includeContent && (
            <p className="flex items-center gap-1.5 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
              <ShieldCheck className="h-4 w-4 shrink-0" /> 켜면 연결한 모든 서비스로 사용자 입력과
              결과가 나가요.
            </p>
          )}
        </CardBody>
      </Card>

      <ErrorBox error={cfg.error ?? save.error ?? test.error} />

      {drafts.length === 0 ? (
        <EmptyState
          icon={<Activity className="h-5 w-5" />}
          title="연결한 추적 서비스가 없어요"
          description="아래 '서비스 추가'에서 Langfuse·LangSmith·OpenTelemetry·Phoenix·Arize·Opik·Weave 중 쓰는 곳을 골라 연결하세요."
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {drafts.map((d) => {
            const kind = kindOf(kinds, d.kind);
            if (!kind) return null;
            return (
              <ProviderCard
                key={d.uid}
                draft={d}
                kind={kind}
                saved={d.id ? savedById.get(d.id) : undefined}
                testing={test.isPending}
                onChange={(next) => update(d.uid, next)}
                onRemove={() => {
                  if (window.confirm(`'${d.name}' 연결을 지울까요? 저장하면 반영돼요.`))
                    setDrafts((cur) => cur.filter((x) => x.uid !== d.uid));
                }}
                onTest={() => test.mutateAsync(d.id)}
              />
            );
          })}
        </div>
      )}

      <div className="flex flex-wrap items-start gap-3">
        <div className="relative">
          <Button
            variant="outline"
            disabled={drafts.length >= MAX_PROVIDERS}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((o) => !o)}
          >
            <Plus className="h-4 w-4" /> 서비스 추가
          </Button>
          {menuOpen && (
            <div
              role="menu"
              className="absolute left-0 z-20 mt-1 w-72 rounded-xl border border-slate-200 bg-white p-1 shadow-lift"
            >
              {kinds.map((k) => (
                <button
                  key={k.kind}
                  type="button"
                  role="menuitem"
                  className="flex w-full flex-col rounded-lg px-3 py-2 text-left hover:bg-slate-100"
                  onClick={() => {
                    setDrafts((cur) => [...cur, newDraft(k)]);
                    setMenuOpen(false);
                  }}
                >
                  <span className="flex items-center gap-1.5 text-sm font-medium text-slate-900">
                    {k.label}
                    {k.experimental && <span className="text-[10px] text-amber-700">실험적</span>}
                  </span>
                  <span className="text-xs text-slate-500">{k.description}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        <Button onClick={submit} disabled={save.isPending}>
          {save.isPending ? "저장하는 중…" : "저장"}
        </Button>
        <p className="basis-full text-xs text-slate-500">
          연결 시험은 저장된 설정으로 해요. 서비스를 추가하거나 값을 바꿨다면 먼저 저장하세요.
        </p>
      </div>
    </div>
  );
}
