import type { NodeType } from "@/lib/api/types";

/** condition 단계의 분기 핸들 id 목록(case id들 + 나머지). */
export function conditionHandles(data: Record<string, unknown>): string[] {
  const cases = (data.cases as { id?: string }[] | undefined) ?? [];
  const ids = cases.map((c) => c.id).filter((x): x is string => Boolean(x));
  const elseId = (data.else as string | undefined) || "else";
  return [...ids, elseId];
}

export interface BranchHandle {
  id: string;
  label: string;
}

/** 분기 단계(condition, question_classifier)의 출구 핸들. 다른 단계는 빈 목록. */
export function branchHandles(type: string, data: Record<string, unknown>): BranchHandle[] {
  if (type === "condition") return conditionHandles(data).map((id) => ({ id, label: id }));
  if (type === "question_classifier") {
    const classes = (data.classes as { id?: string; name?: string }[] | undefined) ?? [];
    return classes
      .filter((c): c is { id: string; name?: string } => Boolean(c.id))
      .map((c) => ({ id: c.id, label: c.name || c.id }));
  }
  // 승인 단계: '반려 시 분기'를 켜면 승인/반려 두 출구(엔진 validator.APPROVAL_HANDLES와 같은 이름)
  if (type === "approval" && data.branch)
    return [
      { id: "approved", label: "승인" },
      { id: "rejected", label: "반려" },
    ];
  return [];
}

/** 실패했을 때 "실패 분기"로 가게 설정했으면 true("fail" 핸들이 생긴다). */
export function hasFailHandle(data: Record<string, unknown>): boolean {
  return data._on_error === "branch";
}

/** 새 단계의 기본 data(스키마 기본값 + 종류별 시작 값). */
export function defaultData(spec: NodeType | undefined): Record<string, unknown> {
  const props = (spec?.input_schema.properties ?? {}) as Record<string, { default?: unknown }>;
  const data: Record<string, unknown> = { label: spec?.label ?? "" };
  for (const [k, p] of Object.entries(props)) if (p.default !== undefined) data[k] = p.default;
  if (spec?.type === "input") data.fields = [{ key: "message", type: "text", required: true }];
  if (spec?.type === "condition") data.cases = [{ id: "c1", when: "" }];
  if (spec?.type === "question_classifier")
    data.classes = [
      { id: "c1", name: "분류 1", description: "" },
      { id: "c2", name: "분류 2", description: "" },
    ];
  return data;
}

/** 병렬 분기 표시(ADR 0010): 한 출구에서 동시에 나가는 갈래 수, 들어오는 갈래 수 */
export function fanCounts(
  edges: { source: string; target: string; sourceHandle?: string | null }[],
  nodeId: string,
): { fanOut: number; fanIn: number } {
  const byHandle = new Map<string, number>();
  let fanIn = 0;
  for (const e of edges) {
    if (e.source === nodeId) {
      const k = e.sourceHandle ?? "";
      byHandle.set(k, (byHandle.get(k) ?? 0) + 1);
    }
    if (e.target === nodeId) fanIn += 1;
  }
  const fanOut = Math.max(0, ...byHandle.values());
  return { fanOut, fanIn };
}
