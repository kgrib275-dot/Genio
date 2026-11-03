import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
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
import { useCanvas } from "@/store/canvas";
import { canEdit, useSession } from "@/store/session";
import { AppNav } from "@/pages/apps/AppNav";

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
  const [run, setRun] = useState<Run | null>(null);
  const [running, setRunning] = useState(false);
  const [showPalette, setShowPalette] = useState(true);
  const [logOpen, setLogOpen] = useState(true);
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
      else toast.info(`고칠 곳이 ${res.errors.length}개 있어요. 빨간 테두리 노드를 확인하세요.`);
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
        right={
          <>
            <span className="text-xs text-slate-400">
              {saving ? "저장 중…" : dirty ? "바뀐 내용 있음" : "작업본 저장됨"}
            </span>
            <Button size="sm" variant="outline" onClick={() => void onValidate()}>
              검사
            </Button>
            {!readOnly && (
              <Button
                size="sm"
                variant="secondary"
                disabled={saveVersion.isPending}
                onClick={() => void onSaveVersion()}
              >
                버전 저장
              </Button>
            )}
            {!readOnly && (
              <Button size="sm" onClick={() => setTestOpen(true)}>
                ▶ 테스트 실행
              </Button>
            )}
          </>
        }
      />
      {generalErrors.length > 0 && (
        <div className="border-b border-red-200 bg-red-50 px-4 py-1.5 text-xs text-red-800">
          {generalErrors.join(" · ")}
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        {!readOnly && (
          <section className="w-[40%] min-w-[320px] max-w-[560px] border-r border-slate-200">
            <BuilderChat appId={appId} />
          </section>
        )}
        <section className="flex min-w-0 flex-1 flex-col">
          <div className="relative flex min-h-0 flex-1">
            {!readOnly && showPalette && (
              <aside className="w-40 shrink-0 overflow-y-auto border-r border-slate-200 bg-slate-50">
                <NodePalette
                  types={specs}
                  onAdd={(t) => {
                    const n = graph.nodes.length;
                    useCanvas
                      .getState()
                      .addNode(
                        t.type,
                        { x: 80 + (n % 4) * 260, y: 60 + Math.floor(n / 4) * 160 },
                        defaultData(t),
                      );
                  }}
                />
              </aside>
            )}
            <div className="relative min-w-0 flex-1 bg-slate-100">
              {!readOnly && (
                <button
                  type="button"
                  className="absolute left-2 top-2 z-10 rounded bg-white px-2 py-1 text-xs shadow"
                  onClick={() => setShowPalette((v) => !v)}
                >
                  {showPalette ? "◀ 노드 목록 숨기기" : "▶ 노드 목록"}
                </button>
              )}
              <FlowCanvas specs={specs} readOnly={readOnly} />
            </div>
            {selected && (
              <aside className="w-80 shrink-0 border-l border-slate-200 bg-white">
                <NodeSettingsPanel
                  node={selected}
                  spec={specs.find((s) => s.type === selected.type)}
                  wsId={ws}
                  nodes={graph.nodes}
                  errors={nodeErrors[selected.id]}
                  readOnly={readOnly}
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
              className="flex w-full items-center justify-between px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              <span>실행 로그</span>
              <span>{logOpen ? "▼" : "▲"}</span>
            </button>
            {logOpen && (
              <div className="max-h-56 overflow-y-auto">
                <RunPanel run={run} steps={stepList} nodes={graph.nodes} />
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
        onRun={(input) => void onRun(input)}
      />
    </div>
  );
}
