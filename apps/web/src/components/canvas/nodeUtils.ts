import type { NodeType } from "@/lib/api/types";

/** condition 노드의 분기 핸들 id 목록(case id들 + 나머지). */
export function conditionHandles(data: Record<string, unknown>): string[] {
  const cases = (data.cases as { id?: string }[] | undefined) ?? [];
  const ids = cases.map((c) => c.id).filter((x): x is string => Boolean(x));
  const elseId = (data.else as string | undefined) || "else";
  return [...ids, elseId];
}

/** 새 노드의 기본 data(스키마 기본값 + 종류별 시작 값). */
export function defaultData(spec: NodeType | undefined): Record<string, unknown> {
  const props = (spec?.input_schema.properties ?? {}) as Record<string, { default?: unknown }>;
  const data: Record<string, unknown> = { label: spec?.label ?? "" };
  for (const [k, p] of Object.entries(props)) if (p.default !== undefined) data[k] = p.default;
  if (spec?.type === "input") data.fields = [{ key: "message", type: "text", required: true }];
  if (spec?.type === "condition") data.cases = [{ id: "c1", when: "" }];
  return data;
}
