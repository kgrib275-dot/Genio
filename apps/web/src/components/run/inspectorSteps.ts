// 실행 단계 목록을 값 확인창이 쓰는 형태로 바꾼다.
import type { InspectorStep } from "@/components/run/ValueInspector";
import type { StoryStep } from "@/lib/api/v5c";

export function inspectorSteps(
  rows: StoryStep[],
  labelOf: (id: string) => string,
): InspectorStep[] {
  return rows.map((s) => ({
    nodeId: s.node_id,
    label: labelOf(s.node_id),
    status: s.status,
    output: s.output,
  }));
}
