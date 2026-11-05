// 지식 처리 캔버스의 자료 모양(화면 그리기와 분리한 순수 함수): 칸 요약 글, 상태, 노드·연결선
import type { CanvasPreview, Stage, StageResult, StageType } from "@/lib/api/kbcanvas";
import type { ChunkMode } from "@/lib/api/types";
import { STEP_INFO, STEP_ORDER } from "@/pages/knowledge/pipelineSteps";

export const MODE_LABEL: Record<ChunkMode, string> = {
  general: "일반",
  parent_child: "부모-자식",
  qa: "질문·답",
};

export type StageStatus = "always" | "on" | "off" | "skipped";

export interface CanvasContext {
  docs: number;
  mode: ChunkMode;
}

export interface StageNodeData extends Record<string, unknown> {
  type: StageType;
  index: number;
  label: string;
  summary: string;
  status: StageStatus;
  ai: boolean;
  selected: boolean;
}

export interface FlowNode {
  id: string;
  type: "stage";
  position: { x: number; y: number };
  data: StageNodeData;
  draggable: false;
  selectable: false;
}

export interface FlowEdge {
  id: string;
  source: string;
  target: string;
  animated: boolean;
}

export const NODE_GAP = 188;

export function usdText(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return "알 수 없음";
  if (usd === 0) return "$0(단가 미등록 모델은 0으로 보여요)";
  return usd < 0.01 ? "$0.01 미만" : `$${usd.toFixed(2)}`;
}

export function stageResult(
  preview: CanvasPreview | undefined,
  type: StageType,
): StageResult | undefined {
  return preview?.stages?.[type];
}

export function stageStatus(step: Stage, res: StageResult | undefined): StageStatus {
  if (STEP_INFO[step.type].always) return "always";
  if (!step.enabled) return "off";
  return res?.skipped ? "skipped" : "on";
}

const n = (v: number | undefined): string => (v ?? 0).toLocaleString("ko-KR");

/** 칸에 보이는 한 줄 요약. 미리 보기를 돌렸으면 실제 숫자를 보여 준다. */
export function stageSummary(
  step: Stage,
  preview: CanvasPreview | undefined,
  ctx: CanvasContext,
): string {
  const res = stageResult(preview, step.type);
  const status = stageStatus(step, res);
  if (status === "off") return "꺼짐";
  if (status === "skipped") return "건너뜀";
  switch (step.type) {
    case "extract":
      return res ? `글 ${n(res.chars)}자` : `문서 ${ctx.docs}개`;
    case "clean":
      return res ? `${n(res.before_chars)}자 → ${n(res.after_chars)}자` : "켜짐";
    case "split":
      return res ? `조각 ${n(res.chunks)}개` : `${MODE_LABEL[ctx.mode]} 방식`;
    case "translate":
      return res?.calls !== undefined
        ? `${res.language ?? ""} · AI ${res.calls}번`.trim()
        : `${step.target_language ?? "영어"}로 번역`;
    case "summarize":
      return res?.calls !== undefined ? `AI ${res.calls}번` : "한 줄 요약";
    case "metadata":
      return res?.tags ? `꼬리표 ${Object.keys(res.tags).length}개` : "켜짐";
    case "image":
      return res?.images !== undefined
        ? `그림 ${res.images}장 → 설명 ${res.described ?? 0}개`
        : "켜짐";
    case "store":
      return preview ? `조각 ${n(preview.total)}개` : "검색용으로 저장";
  }
}

/** 캔버스 위쪽 한 줄: "문서 3개 → 조각 42개" */
export function flowHeadline(preview: CanvasPreview | undefined, ctx: CanvasContext): string {
  if (!preview) return `문서 ${ctx.docs}개 · 미리 보기를 누르면 단계마다 어떻게 바뀌는지 보여 줘요`;
  return `문서 ${ctx.docs}개 → (미리 본 문서에서) 조각 ${n(preview.total)}개`;
}

export function buildFlow(
  steps: Stage[],
  preview: CanvasPreview | undefined,
  ctx: CanvasContext,
  selected: StageType,
): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const ordered = STEP_ORDER.map((t) => steps.find((s) => s.type === t)).filter(
    (s): s is Stage => s !== undefined,
  );
  const nodes: FlowNode[] = ordered.map((s, i) => ({
    id: s.type,
    type: "stage",
    position: { x: i * NODE_GAP, y: 0 },
    draggable: false,
    selectable: false,
    data: {
      type: s.type,
      index: i + 1,
      label: STEP_INFO[s.type].label,
      summary: stageSummary(s, preview, ctx),
      status: stageStatus(s, stageResult(preview, s.type)),
      ai: STEP_INFO[s.type].ai,
      selected: s.type === selected,
    },
  }));
  const edges: FlowEdge[] = ordered.slice(1).map((s, i) => {
    const prev = ordered[i] as Stage;
    return {
      id: `${prev.type}->${s.type}`,
      source: prev.type,
      target: s.type,
      animated: Boolean(preview) && prev.enabled && s.enabled,
    };
  });
  return { nodes, edges };
}

/** AI를 부르는 켜진 단계가 있을 때 미리 보기·다시 나누기 앞에 보여 줄 안내 */
export function aiWarning(aiStages: StageType[]): string | null {
  if (aiStages.length === 0) return null;
  const names = aiStages.map((t) => STEP_INFO[t].label).join("·");
  return `${names} 단계는 AI를 불러서 비용이 들어요. 미리 보기는 앞의 조각 3개(그림 3장)에만 AI를 불러요.`;
}
