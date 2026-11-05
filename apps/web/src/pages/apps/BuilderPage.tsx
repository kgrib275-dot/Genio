import {
  ChevronDown,
  ChevronUp,
  MessageCircle,
  Play,
  Plus,
  Save,
  ShieldCheck,
  X,
} from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { BuilderChat } from "@/components/builder-chat/BuilderChat";
import { FlowCanvas } from "@/components/canvas/FlowCanvas";
import { NodePalette } from "@/components/canvas/NodePalette";
import { NodeSettingsPanel } from "@/components/canvas/NodeSettingsPanel";
import { defaultData } from "@/components/canvas/nodeUtils";
import { RunPanel } from "@/components/canvas/RunPanel";
import { TestRunDialog } from "@/components/canvas/TestRunDialog";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast-store";
import { saveDraft, startRun, useApp, useSaveVersion, validateGraph } from "@/lib/api/apps";
import { streamRunEvents } from "@/lib/api/builder";
import { ApiError } from "@/lib/api/client";
import { normalizeGraph, type Run, type RunStep } from "@/lib/api/types";
import { useNodeTypes } from "@/lib/api/workspace";
import { fixRequestMessage } from "@/lib/api/v5c";
import { setPendingPrompt } from "@/store/pendingPrompt";
import { useCanvas } from "@/store/canvas";
import { canEdit, useSession } from "@/store/session";
import { AppNav } from "@/pages/apps/AppNav";

// 대화로 시험하기(Dify 미리 보기). 열 때만 받아 온다.
const PreviewChatPanel = lazy(() => import("@/components/chat/PreviewChatPanel"));

/** 사용자 편집 후 잠시 기다렸다가 작업본을 서버에 저장한다. */
function useDraftAutosave(appId: string) {
  const editSeq = useCanvas((s) => s.editSeq);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!appId || editSeq === 0) return;
    const seq = editSeq;
    const t = setTimeout(async () => {
      setSaving(true);
      try {
        await saveDraft(appId, useCanvas.getState().graph);
        if (useCanvas.getState().editSeq === seq) useCanvas.getState().markSaved();
      } catch (err) {
        toast.error(err);
      } finally {
        setSaving(false);
      }
    }, 800);
    return () => clearTimeout(t);
  }, [appId, editSeq]);
  return saving;
}

export default function BuilderPage() {
  const { id: appId = "" } = useParams();
  const { workspaceId: ws, role } = useSession();
  const app = useApp(appId);
  const nodeTypes = useNodeTypes(ws);
  const saveVersion = useSaveVersion(appId);
  const graph = useCanvas((s) => s.graph);
  const dirty = useCanvas((s) => s.dirty);
  const selectedId = useCanvas((s) => s.selectedId);
  const nodeErrors = useCanvas((s) => s.nodeErrors);
  const generalErrors = useCanvas((s) => s.generalErrors);
  const steps = useCanvas((s) => s.steps);
  const saving = useDraftAutosave(appId);
  const [testOpen, setTestOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [run, setRun] = useState<Run | null>(null);
  const [running, setRunning] = useState(false);
  const [showPalette, setShowPalette] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  // 좁은 화면(모바일·태블릿)에서는 패널을 탭으로 하나씩 보여 준다
  const [mobileTab, setMobileTab] = useState<"chat" | "canvas" | "settings">("chat");
  // 실행 화면의 '빌더에게 고쳐 달라고 하기'(?fix=실행id): 빌더 챗에 고쳐 달라는 메시지를 보낸다
  const [params, setParams] = useSearchParams();
  const [promptNonce, setPromptNonce] = useState(0);
  const fixRunId = params.get("fix");
  useEffect(() => {
    if (!fixRunId || !appId) return;
    setPendingPrompt(appId, fixRequestMessage(fixRunId));
    setMobileTab("chat");
    setPromptNonce((n) => n + 1);
    const next = new URLSearchParams(params);
    next.delete("fix");
    setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fixRunId, appId]);
  const loadedFor = useRef<string>("");
  const abortRef = useRef<AbortController | null>(null);
  const readOnly = !canEdit(role);

  useEffect(() => {
    if (app.data && loadedFor.current !== appId) {
      loadedFor.current = appId;
      useCanvas.getState().load(appId, normalizeGraph(app.data.draft_graph));
      setRun(null);
    }
  }, [app.data, appId]);

  useEffect(() => () => abortRef.current?.abort(), []);

  if (app.isLoading) return <Loading />;
  if (app.error)
    return (
      <div className="p-8">
        <ErrorBox error={app.error} />
      </div>
    );
  if (!app.data) return null;

  const specs = nodeTypes.data ?? [];
  const selected = graph.nodes.find((n) => n.id === selectedId);
  const inputNode = graph.nodes.find((n) => n.type === "input");

  const flush = async () => {
    if (useCanvas.getState().dirty) {
      await saveDraft(appId, useCanvas.getState().graph);
      useCanvas.getState().markSaved();
    }
  };

  const onValidate = async () => {
    try {
      await flush();
      const res = await validateGraph(appId);
      useCanvas.getState().setErrors(res.errors);
      if (res.valid) toast.success("문제가 없어요. 버전으로 저장할 수 있어요.");
      else toast.info(`고칠 곳이 ${res.errors.length}개 있어요. 빨간 테두리 단계를 확인하세요.`);
    } catch (err) {
      toast.error(err);
    }
  };

  const onSaveVersion = async () => {
    try {
      await flush();
      const v = await saveVersion.mutateAsync({});
      useCanvas.getState().setErrors([]);
      toast.success(`버전 ${v.version}으로 저장했어요.`);
    } catch (err) {
      if (err instanceof ApiError && err.errors.length) useCanvas.getState().setErrors(err.errors);
      toast.error(err);
    }
  };

  const onRun = async (input: Record<string, unknown>) => {
    setRunning(true);
    try {
      await flush();
      const r = await startRun(appId, input);
      setTestOpen(false);
      setLogOpen(true);
      setRun(r);
      useCanvas.getState().resetSteps();
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      void streamRunEvents(
        r.id,
        (ev) => {
          if (ev.event === "step") useCanvas.getState().setStep(ev.data as RunStep);
          else if (ev.event === "run" || ev.event === "end") setRun(ev.data as Run);
        },
        ctrl.signal,
      ).catch((err: unknown) => {
        if (!(err instanceof DOMException && err.name === "AbortError")) toast.error(err);
      });
    } catch (err) {
      if (err instanceof ApiError && err.errors.length) useCanvas.getState().setErrors(err.errors);
      toast.error(err);
    } finally {
      setRunning(false);
    }
  };

  const stepList = Object.values(steps).sort((a, b) =>
    (a.started_at ?? "").localeCompare(b.started_at ?? ""),
  );

  return (
    <div className="flex h-full flex-col">
      <AppNav
        appId={appId}
        title={app.data.name}
        icon={app.data.icon}
        help="builder"
        right={
          <>
            <span className="mr-1 hidden items-center gap-1.5 text-xs text-slate-400 sm:flex">
              <span
                className={`h-1.5 w-1.5 rounded-full ${saving ? "animate-pulse bg-amber-400" : dirty ? "bg-amber-400" : "bg-emerald-500"}`}
              />
              {saving ? "저장 중…" : dirty ? "바뀐 내용 있음" : "자동 저장됨"}
            </span>
            <Button size="sm" variant="outline" onClick={() => void onValidate()}>
              <ShieldCheck className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">검사</span>
            </Button>
            {!readOnly && (
              <Button
                size="sm"
                variant="outline"
                disabled={saveVersion.isPending}
                onClick={() => void onSaveVersion()}
              >
                <Save className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">버전 저장</span>
              </Button>
            )}
            {!readOnly && app.data.type === "chat" && (
              <Button
                size="sm"
                variant="outline"
                title="지금 만든 흐름과 대화해 봐요(로그에는 남지 않아요)"
                onClick={async () => {
                  // 바뀐 내용이 있으면 먼저 저장해 최신 작업본으로 대화한다
                  if (useCanvas.getState().dirty) {
                    try {
                      await saveDraft(appId, useCanvas.getState().graph);
                      useCanvas.getState().markSaved();
                    } catch (err) {
                      toast.error(err);
                      return;
                    }
                  }
                  setPreviewOpen(true);
                }}
              >
                <MessageCircle className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">대화로 시험</span>
              </Button>
            )}
            {!readOnly && (
              <Button size="sm" onClick={() => setTestOpen(true)}>
                <Play className="h-3.5 w-3.5" /> 테스트
                <span className="hidden sm:inline">실행</span>
              </Button>
            )}
          </>
        }
      />
      {generalErrors.length > 0 && (
        <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-xs text-red-800">
          {generalErrors.join(" · ")}
        </div>
      )}
      <div
        role="tablist"
        aria-label="빌더 화면"
        className="flex shrink-0 gap-1 border-b border-slate-200 bg-white px-2 py-1.5 lg:hidden"
      >
        {(
          [
            ...(!readOnly ? [["chat", "빌더 챗"] as const] : []),
            ["canvas", "캔버스"] as const,
            ["settings", selected ? "설정 ●" : "설정"] as const,
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={mobileTab === key}
            onClick={() => setMobileTab(key)}
            className={`flex-1 rounded-md px-2 py-1.5 text-[13px] font-medium ${mobileTab === key ? "bg-indigo-50 text-indigo-700" : "text-slate-500"}`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="flex min-h-0 flex-1">
        {!readOnly && (
          <section
            className={`w-full shrink-0 border-r border-slate-200 lg:block lg:w-[380px] ${mobileTab === "chat" ? "block" : "hidden"}`}
          >
            <BuilderChat appId={appId} promptNonce={promptNonce} />
          </section>
        )}
        <section
          className={`min-w-0 flex-1 flex-col lg:flex ${mobileTab === "chat" && !readOnly ? "hidden" : "flex"}`}
        >
          <div className="relative flex min-h-0 flex-1">
            <div
              className={`relative min-w-0 flex-1 bg-slate-50 lg:block ${mobileTab === "settings" ? "hidden" : "block"}`}
            >
              {!readOnly && (
                <div className="absolute left-3 top-3 z-10">
                  <Button
                    size="sm"
                    variant="outline"
                    className="shadow-lift"
                    onClick={() => setShowPalette((v) => !v)}
                  >
                    {showPalette ? <X className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
                    단계 추가
                  </Button>
                  {showPalette && (
                    <div className="mt-2 w-72 rounded-xl border border-slate-200 bg-white shadow-lift">
                      <NodePalette
                        types={specs}
                        onAdd={(t) => {
                          const n = graph.nodes.length;
                          useCanvas
                            .getState()
                            .addNode(
                              t.type,
                              { x: 80 + (n % 4) * 280, y: 60 + Math.floor(n / 4) * 170 },
                              defaultData(t),
                            );
                          setShowPalette(false);
                        }}
                      />
                    </div>
                  )}
                </div>
              )}
              <FlowCanvas specs={specs} readOnly={readOnly} />
            </div>
            {mobileTab === "settings" && !selected && (
              <p className="flex-1 p-6 text-center text-sm text-slate-500 lg:hidden">
                캔버스에서 단계를 누르면 여기에서 설정을 고칠 수 있어요.
              </p>
            )}
            {selected && (
              <aside
                className={`w-full shrink-0 border-l border-slate-200 bg-white lg:block lg:w-[340px] ${mobileTab === "settings" ? "block" : "hidden"}`}
              >
                <NodeSettingsPanel
                  node={selected}
                  spec={specs.find((s) => s.type === selected.type)}
                  wsId={ws}
                  nodes={graph.nodes}
                  errors={nodeErrors[selected.id]}
                  readOnly={readOnly}
                  appId={appId}
                  lastStep={steps[selected.id]}
                  onChange={(data) => useCanvas.getState().updateNodeData(selected.id, data)}
                  onDelete={() => useCanvas.getState().removeNode(selected.id)}
                  onClose={() => useCanvas.getState().select(null)}
                />
              </aside>
            )}
          </div>
          <div className="border-t border-slate-200 bg-white">
            <button
              type="button"
              onClick={() => setLogOpen((v) => !v)}
              className="flex w-full items-center gap-2 px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              <span>실행 로그</span>
              {run && (
                <span className="text-slate-400">
                  ·{" "}
                  {{
                    queued: "대기",
                    running: "실행 중",
                    succeeded: "성공",
                    failed: "실패",
                    waiting_approval: "승인 대기",
                  }[run.status] ?? run.status}
                </span>
              )}
              {logOpen ? (
                <ChevronDown className="ml-auto h-4 w-4" />
              ) : (
                <ChevronUp className="ml-auto h-4 w-4" />
              )}
            </button>
            {logOpen && (
              <div className="max-h-64 overflow-y-auto border-t border-slate-100">
                <RunPanel run={run} steps={stepList} nodes={graph.nodes} selectedId={selectedId} />
              </div>
            )}
          </div>
        </section>
      </div>
      <TestRunDialog
        open={testOpen}
        onClose={() => setTestOpen(false)}
        inputNode={inputNode}
        running={running}
        canBatch={app.data?.type === "workflow"}
        onRun={(input) => void onRun(input)}
      />
      {previewOpen && (
        <Suspense fallback={null}>
          <PreviewChatPanel appId={appId} onClose={() => setPreviewOpen(false)} />
        </Suspense>
      )}
    </div>
  );
}
