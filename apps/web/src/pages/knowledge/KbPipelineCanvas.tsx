// v0.9 문서 처리 캔버스: 꺼내기 → 정리 → 나누기 → 번역 → 요약 붙이기 → 꼬리표 → 이미지 설명 → 저장
// 칸을 누르면 설정과 그 단계가 한 일(미리 보기)이 아래에 나온다. 저장하기 전에는 아무것도 바뀌지 않는다.
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Eye, FileUp, LayoutTemplate, Sparkles } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { KbImage } from "@/components/knowledge/KbImage";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import {
  useImageEstimate,
  usePipelineTemplates,
  usePreviewCanvas,
  type CanvasPreview,
  type Stage,
  type StageType,
} from "@/lib/api/kbcanvas";
import type { KbDocumentV2, KbSettings, KnowledgeBaseV2, PipelineStep } from "@/lib/api/types";
import { normalizeKbSettings } from "@/lib/api/types";
import { useUpdateKnowledgeBase } from "@/lib/api/v2";
import { useReprocessKb } from "@/lib/api/v6kb";
import { cn } from "@/lib/cn";
import { useIsDark } from "@/store/theme";
import {
  MODE_LABEL,
  aiWarning,
  buildFlow,
  flowHeadline,
  stageResult,
  usdText,
  type StageNodeData,
} from "@/pages/knowledge/kbCanvasModel";
import { StepSettings } from "@/pages/knowledge/KbStepSettings";
import {
  STEP_INFO,
  enabledAiStages,
  normalizePipeline,
  templateToDraft,
} from "@/pages/knowledge/pipelineSteps";

type StageNodeView = StageNodeData & {
  onToggle?: (type: StageType, on: boolean) => void;
};
type StageFlowNode = Node<StageNodeView, "stage">;

const STATUS_TEXT: Record<StageNodeData["status"], string> = {
  always: "항상",
  on: "켜짐",
  off: "꺼짐",
  skipped: "건너뜀",
};

function StageNode({ data }: NodeProps<StageFlowNode>) {
  const optional = data.status !== "always";
  return (
    <div
      data-testid={`stage-${data.type}`}
      className={cn(
        "w-[168px] cursor-pointer rounded-xl border bg-white p-2.5 text-left shadow-card transition-shadow",
        data.selected ? "border-indigo-400 ring-4 ring-indigo-500/15" : "border-slate-200",
        data.status === "off" && "border-dashed opacity-70",
        data.status === "skipped" && "border-amber-300 bg-amber-50",
      )}
    >
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !bg-slate-300" />
      <div className="flex items-center gap-1.5">
        <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[11px] font-bold text-indigo-700">
          {data.index}
        </span>
        <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-slate-900">
          {data.label}
        </span>
        {data.ai && (
          <span
            className="rounded bg-violet-100 px-1 text-[10px] font-bold text-violet-700"
            title="AI를 불러서 비용이 들어요"
          >
            AI
          </span>
        )}
      </div>
      <p className="mt-1.5 truncate text-[11px] text-slate-500" title={data.summary}>
        {data.summary}
      </p>
      <div className="mt-1.5 flex items-center justify-between">
        <span
          className={cn(
            "rounded-full px-1.5 py-0.5 text-[10px] font-medium",
            data.status === "on" && "bg-emerald-100 text-emerald-700",
            data.status === "always" && "bg-slate-100 text-slate-500",
            data.status === "off" && "bg-slate-100 text-slate-400",
            data.status === "skipped" && "bg-amber-100 text-amber-800",
          )}
        >
          {STATUS_TEXT[data.status]}
        </span>
        {optional && (
          <label className="nodrag nopan flex items-center gap-1 text-[11px] text-slate-600">
            <input
              type="checkbox"
              aria-label={`${data.label} 켜기`}
              checked={data.status !== "off"}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => data.onToggle?.(data.type, e.target.checked)}
            />
            켜기
          </label>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !bg-slate-300" />
    </div>
  );
}

const nodeTypes = { stage: StageNode };

/** 한 줄로 이어진 8칸. 칸을 누르면 선택, 칸 안의 '켜기'로 켜고 끈다. */
export function PipelineCanvas({
  steps,
  preview,
  docs,
  mode,
  selected,
  onSelect,
  onToggle,
}: {
  steps: Stage[];
  preview: CanvasPreview | undefined;
  docs: number;
  mode: KbSettings["chunk_mode"];
  selected: StageType;
  onSelect: (t: StageType) => void;
  onToggle: (t: StageType, on: boolean) => void;
}) {
  const dark = useIsDark();
  const flow = useMemo(
    () => buildFlow(steps, preview, { docs, mode }, selected),
    [steps, preview, docs, mode, selected],
  );
  const nodes = useMemo<StageFlowNode[]>(
    () => flow.nodes.map((n) => ({ ...n, data: { ...n.data, onToggle } })),
    [flow.nodes, onToggle],
  );
  return (
    <div
      className="h-[150px] overflow-hidden rounded-xl border border-slate-200 bg-slate-50"
      data-testid="pipeline-canvas"
    >
      <ReactFlow
        nodes={nodes}
        edges={flow.edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, n) => onSelect(n.id as StageType)}
        colorMode={dark ? "dark" : "light"}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        preventScrolling={false}
        minZoom={0.5}
        maxZoom={1.3}
        defaultViewport={{ x: 12, y: 18, zoom: 1 }}
        proOptions={{ hideAttribution: true }}
        aria-label="문서 처리 캔버스"
      >
        <Background gap={18} size={1} />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
      <span className="sr-only">{flowHeadline(preview, { docs, mode })}</span>
    </div>
  );
}

function Sample({ label, text, tone }: { label: string; text?: string; tone?: "from" | "to" }) {
  if (!text) return null;
  return (
    <div
      className={cn(
        "rounded-lg border p-2 text-xs",
        tone === "to" ? "border-emerald-200 bg-emerald-50/40" : "border-slate-200",
      )}
    >
      <p className="mb-1 font-medium text-slate-500">{label}</p>
      <p className="max-h-28 overflow-y-auto whitespace-pre-wrap text-slate-700">{text}</p>
    </div>
  );
}

function AiHint({ calls, full, usd }: { calls?: number; full?: number; usd?: number | null }) {
  if (calls === undefined) return null;
  return (
    <p className="rounded-lg bg-violet-50 px-2.5 py-1.5 text-xs text-violet-900">
      AI 호출 <b>{calls}번</b>
      {full !== undefined && full > calls && ` (전부 다시 나누면 약 ${full}번)`} · 전체 예상 비용{" "}
      <b>{usdText(usd)}</b>
    </p>
  );
}

/** 선택한 단계가 샘플 문서에 한 일 */
export function StagePreview({
  type,
  preview,
}: {
  type: StageType;
  preview: CanvasPreview | undefined;
}) {
  if (!preview)
    return (
      <p className="text-xs text-slate-500">
        위의 <b>미리 보기</b>를 누르면 이 단계가 샘플 문서를 어떻게 바꾸는지 보여 줘요. 저장하지
        않고 확인만 해요.
      </p>
    );
  const res = stageResult(preview, type);
  const skipped = res?.skipped;
  const imageChunks = preview.chunks.filter((c) => c.kind === "image");
  return (
    <div className="space-y-2 text-sm" data-testid={`preview-${type}`}>
      {skipped && (
        <p className="rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs text-amber-900">{skipped}</p>
      )}
      {type === "extract" && (
        <>
          <Badge tone="indigo">글 {(res?.chars ?? 0).toLocaleString("ko-KR")}자</Badge>
          <Sample label="꺼낸 글의 앞부분" text={res?.sample} />
        </>
      )}
      {type === "clean" &&
        (res?.enabled ? (
          <div className="grid gap-2 sm:grid-cols-2">
            <Sample
              label={`정리 전 (${(res.before_chars ?? 0).toLocaleString("ko-KR")}자)`}
              text={res.before_sample}
            />
            <Sample
              label={`정리 후 (${(res.after_chars ?? 0).toLocaleString("ko-KR")}자)`}
              text={res.after_sample}
              tone="to"
            />
          </div>
        ) : (
          <p className="text-xs text-slate-500">이 단계가 꺼져 있어 글을 그대로 써요.</p>
        ))}
      {type === "split" && (
        <>
          <Badge tone="indigo">
            조각 {res?.chunks ?? 0}개 · {MODE_LABEL[preview.chunk_mode]}
          </Badge>
          <ol className="space-y-1.5">
            {(res?.samples ?? []).map((s, i) => (
              <li key={i} className="rounded-lg border border-slate-200 p-2 text-xs text-slate-700">
                <span className="mr-1 text-slate-400">#{i + 1}</span>
                {typeof s === "string" ? s : ""}
              </li>
            ))}
          </ol>
        </>
      )}
      {type === "translate" &&
        (res?.enabled === false ? (
          <p className="text-xs text-slate-500">이 단계가 꺼져 있어요.</p>
        ) : (
          <>
            <AiHint calls={res?.calls} full={res?.calls_full} usd={res?.estimated_cost_usd} />
            {(res?.samples ?? []).map((s, i) =>
              typeof s === "string" ? null : (
                <div key={i} className="grid gap-2 sm:grid-cols-2">
                  <Sample label="번역 전" text={s.before} />
                  <Sample label={`번역 후(${res?.language ?? ""})`} text={s.after} tone="to" />
                </div>
              ),
            )}
          </>
        ))}
      {type === "summarize" &&
        (res?.enabled === false ? (
          <p className="text-xs text-slate-500">이 단계가 꺼져 있어요.</p>
        ) : (
          <>
            <AiHint calls={res?.calls} full={res?.calls_full} usd={res?.estimated_cost_usd} />
            {(res?.samples ?? []).map((s, i) =>
              typeof s === "string" ? null : (
                <Sample key={i} label="붙은 한 줄 요약" text={s.summary} tone="to" />
              ),
            )}
          </>
        ))}
      {type === "metadata" &&
        (res?.tags && Object.keys(res.tags).length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(res.tags).map(([k, v]) => (
              <Badge key={k} tone="blue">
                {k}={v}
              </Badge>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-500">붙은 꼬리표가 없어요.</p>
        ))}
      {type === "image" &&
        (res?.enabled === false ? (
          <p className="text-xs text-slate-500">
            이 단계가 꺼져 있어요. 켜면 문서 속 그림을 AI가 글로 설명해 검색에 써요.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-1.5 text-xs">
              <Badge tone="indigo">그림 {res?.images ?? 0}장</Badge>
              <Badge tone="green">설명 {res?.described ?? 0}개</Badge>
              {(res?.failed ?? 0) > 0 && <Badge tone="red">실패 {res?.failed}개</Badge>}
              {(res?.duplicates ?? 0) > 0 && <Badge>중복 {res?.duplicates}장 뺌</Badge>}
              {(res?.too_small ?? 0) > 0 && <Badge>작아서 {res?.too_small}장 뺌</Badge>}
              {(res?.cut ?? 0) > 0 && <Badge>미리 보기는 3장까지({res?.cut}장 더 있음)</Badge>}
            </div>
            <AiHint calls={res?.calls} full={res?.calls_full} usd={res?.estimated_cost_usd} />
            <ul className="space-y-2">
              {imageChunks.map((c) => (
                <li key={c.index} className="flex gap-2.5 rounded-lg border border-slate-200 p-2">
                  {c.thumb ? (
                    <img
                      src={c.thumb}
                      alt={c.image?.caption ?? "문서 속 그림"}
                      className="h-16 w-20 shrink-0 rounded border border-slate-200 bg-white object-contain"
                    />
                  ) : (
                    <KbImage image={{ file_id: "", caption: c.image?.caption }} />
                  )}
                  <p className="text-xs text-slate-700">
                    {c.image?.page ? <b>{c.image.page}쪽 · </b> : null}
                    {c.image?.caption ?? c.content}
                  </p>
                </li>
              ))}
            </ul>
            {(res?.errors ?? []).map((e, i) => (
              <p key={i} className="text-xs text-red-600">
                {e}
              </p>
            ))}
          </>
        ))}
      {type === "store" && (
        <>
          <Badge tone="indigo">조각 {preview.total}개를 저장해요</Badge>
          <ul className="list-disc pl-4 text-xs text-slate-600">
            {preview.log.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export function PipelineDialog({
  ws,
  kb,
  docs,
  onClose,
}: {
  ws: string;
  kb: KnowledgeBaseV2;
  docs: KbDocumentV2[];
  onClose: () => void;
}) {
  const base = normalizeKbSettings(kb.settings);
  const [steps, setSteps] = useState<Stage[]>(() => normalizePipeline(base.pipeline));
  const [overrides, setOverrides] = useState<Partial<KbSettings>>({});
  const [selected, setSelected] = useState<StageType>("extract");
  const [tplId, setTplId] = useState("");
  const update = useUpdateKnowledgeBase(ws);
  const reprocess = useReprocessKb(kb.id);
  const preview = usePreviewCanvas(kb.id);
  const templates = usePipelineTemplates();
  const [docId, setDocId] = useState(docs[0]?.id ?? "");
  const fileRef = useRef<HTMLInputElement>(null);
  const mode = overrides.chunk_mode ?? base.chunk_mode;
  const imageStep = steps.find((s) => s.type === "image");
  const estimate = useImageEstimate(
    kb.id,
    { maxImages: imageStep?.max_images ?? 20, minSize: imageStep?.min_size ?? 100 },
    Boolean(imageStep?.enabled),
  );
  const aiStages = enabledAiStages(steps);
  const warning = aiWarning(aiStages);
  const current = steps.find((s) => s.type === selected) ?? (steps[0] as Stage);
  const info = STEP_INFO[selected];

  const setStep = (s: Stage) => setSteps(steps.map((x) => (x.type === s.type ? s : x)));
  const toggle = (type: StageType, on: boolean) =>
    setSteps((cur) => cur.map((x) => (x.type === type ? { ...x, enabled: on } : x)));
  const patch = () => ({ pipeline: steps as unknown as PipelineStep[], ...overrides });
  const run = (file?: File) =>
    preview.mutate({
      file,
      documentId: file ? undefined : docId,
      settings: { pipeline: steps, ...overrides },
    });

  const applyTemplate = () => {
    const tpl = templates.data?.find((t) => t.id === tplId);
    if (!tpl) return;
    if (
      !window.confirm(
        `'${tpl.name}' 모음을 적용할까요? 지금 처리 순서와 나누기 설정이 바뀌어요. 저장하기 전에는 지식베이스에 반영되지 않아요.`,
      )
    )
      return;
    const draft = templateToDraft(tpl);
    setSteps(draft.steps);
    setOverrides(draft.overrides);
    preview.reset();
    toast.success(`'${tpl.name}' 모음을 불러왔어요. 확인하고 저장하세요.`);
  };

  const confirmReprocess = (): boolean => {
    if (aiStages.length === 0) return true;
    const lines: string[] = [];
    if (imageStep?.enabled) {
      const d = estimate.data;
      lines.push(
        d
          ? `이미지 설명: 그림 ${d.images}장 → AI 약 ${d.vision_calls}번, 예상 비용 ${usdText(d.estimated_cost_usd)}`
          : "이미지 설명: 그림 수를 아직 세지 못했어요",
      );
    }
    const text = aiStages.filter((t) => t !== "image").map((t) => STEP_INFO[t].label);
    if (text.length)
      lines.push(
        `${text.join("·")}: 조각마다 AI를 불러요(문서 ${docs.length}개). 미리 보기에서 호출 수를 확인하세요`,
      );
    return window.confirm(
      `다시 나누면 AI가 호출돼 비용이 들어요.\n\n${lines.join("\n")}\n\n계속할까요?`,
    );
  };

  const save = (again: boolean) => {
    if (again && !confirmReprocess()) return;
    update.mutate(
      { id: kb.id, settings: patch() },
      {
        onSuccess: () => {
          if (!again) {
            toast.success("처리 순서를 저장했어요. 새로 올리는 문서부터 반영돼요.");
            onClose();
            return;
          }
          reprocess.mutate(undefined, {
            onSuccess: (r) => {
              toast.success(`저장하고 문서 ${r.queued}개를 다시 나누는 중이에요.`);
              onClose();
            },
          });
        },
      },
    );
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title="문서 처리 캔버스"
      wide
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            취소
          </Button>
          <Button
            variant="outline"
            disabled={update.isPending || reprocess.isPending || docs.length === 0}
            onClick={() => save(true)}
          >
            저장하고 모든 문서 다시 나누기
          </Button>
          <Button disabled={update.isPending} onClick={() => save(false)}>
            저장
          </Button>
        </>
      }
    >
      <div className="space-y-4 text-sm">
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[12rem] flex-1">
            <label htmlFor="pl-tpl" className="mb-1 block text-xs font-medium text-slate-600">
              <LayoutTemplate className="mr-1 inline h-3.5 w-3.5" />
              처리 순서 모음
            </label>
            <Select id="pl-tpl" value={tplId} onChange={(e) => setTplId(e.target.value)}>
              <option value="">모음을 골라 한 번에 바꾸기…</option>
              {(templates.data ?? []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </Select>
          </div>
          <Button variant="outline" disabled={!tplId} onClick={applyTemplate}>
            적용
          </Button>
          <div className="flex flex-wrap gap-2">
            {docs.length > 0 && (
              <>
                <Select
                  aria-label="미리 볼 문서"
                  className="max-w-[12rem]"
                  value={docId}
                  onChange={(e) => setDocId(e.target.value)}
                >
                  {docs.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.filename}
                    </option>
                  ))}
                </Select>
                <Button
                  variant="outline"
                  disabled={preview.isPending || !docId}
                  onClick={() => run()}
                >
                  <Eye className="h-4 w-4" /> 이 문서로 미리 보기
                </Button>
              </>
            )}
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              aria-label="미리 볼 파일"
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) run(f);
              }}
            />
            <Button
              variant="outline"
              disabled={preview.isPending}
              onClick={() => fileRef.current?.click()}
            >
              <FileUp className="h-4 w-4" /> 파일로 미리 보기
            </Button>
          </div>
        </div>
        {templates.data?.find((t) => t.id === tplId) && (
          <p className="text-xs text-slate-500">
            {templates.data.find((t) => t.id === tplId)?.description}
          </p>
        )}
        {warning && (
          <p className="flex gap-1.5 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
            <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{warning}</span>
          </p>
        )}
        <div>
          <p className="mb-1 text-xs text-slate-500">
            {flowHeadline(preview.data, { docs: docs.length, mode })}
          </p>
          <PipelineCanvas
            steps={steps}
            preview={preview.data}
            docs={docs.length}
            mode={mode}
            selected={selected}
            onSelect={setSelected}
            onToggle={toggle}
          />
        </div>
        {preview.isPending && <p className="text-xs text-slate-500">나눠 보는 중…</p>}
        <ErrorBox error={preview.error ?? update.error ?? reprocess.error} />
        <div className="grid gap-4 lg:grid-cols-2">
          <section
            className="space-y-2 rounded-xl border border-slate-200 p-3"
            aria-label={`${info.label} 설정`}
          >
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <p className="font-semibold text-slate-900">{info.label}</p>
                <p className="text-xs text-slate-500">{info.desc}</p>
              </div>
              {info.always ? (
                <Badge>항상</Badge>
              ) : (
                <label className="flex shrink-0 items-center gap-1.5 text-xs">
                  <input
                    type="checkbox"
                    aria-label={`${info.label} 켜기 (설정)`}
                    checked={current.enabled}
                    onChange={(e) => toggle(selected, e.target.checked)}
                  />
                  켜기
                </label>
              )}
            </div>
            <StepSettings step={current} onChange={setStep} mode={mode} kbId={kb.id} />
          </section>
          <section className="space-y-2 rounded-xl border border-slate-200 p-3">
            <p className="font-semibold text-slate-900">이 단계가 한 일</p>
            <StagePreview type={selected} preview={preview.data} />
          </section>
        </div>
      </div>
    </Dialog>
  );
}
