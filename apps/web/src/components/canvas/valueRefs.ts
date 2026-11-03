// '값 끌어오기'(기능 정의서 S2) 로직: 앞 단계가 내는 값 목록, {{ }} ↔ 읽기 쉬운 표시 변환, 끼워 넣기, 자동완성.
// 저장 형식은 늘 {{n1.message}}이고, 보통 모드에서는 «사용자 입력 › 메시지»로 보여 준다.
import { keyLabel } from "@/lib/dataLabels";

export interface RefNode {
  id: string;
  type: string;
  data: Record<string, unknown>;
}

export interface RefEdge {
  source: string;
  target: string;
}

export interface RefSpec {
  type: string;
  label?: string;
  output_schema?: Record<string, unknown>;
}

export interface ValueOption {
  /** 중괄호 안 표현식(예: n1.message) */
  expr: string;
  /** 단계 이름 › 항목 이름 */
  label: string;
  group: string;
  item: string;
}

export interface ValueGroup {
  id: string;
  label: string;
  items: ValueOption[];
}

const REF = /\{\{\s*([^{}]+?)\s*\}\}/g;
const CHIP = /«([^«»]+)»/g;

/** nodeId 앞쪽(선을 거슬러 올라가 닿는) 단계 id들 */
export function upstreamIds(nodeId: string, edges: RefEdge[]): Set<string> {
  const back = new Map<string, string[]>();
  for (const e of edges) back.set(e.target, [...(back.get(e.target) ?? []), e.source]);
  const seen = new Set<string>();
  const stack = [...(back.get(nodeId) ?? [])];
  while (stack.length) {
    const cur = stack.pop() as string;
    if (seen.has(cur) || cur === nodeId) continue;
    seen.add(cur);
    stack.push(...(back.get(cur) ?? []));
  }
  return seen;
}

function propsOf(schema: unknown): Record<string, Record<string, unknown>> {
  const p = (schema as { properties?: Record<string, Record<string, unknown>> } | undefined)
    ?.properties;
  return p ?? {};
}

/** 단계 하나가 내는 값들 [{key, label}] */
export function nodeOutputs(node: RefNode, spec?: RefSpec): { key: string; label: string }[] {
  const out = new Map<string, string>();
  const add = (key: unknown, label?: unknown) => {
    if (typeof key !== "string" || !key || key.startsWith("__")) return;
    if (!out.has(key)) out.set(key, typeof label === "string" && label ? label : keyLabel(key));
  };
  const d = node.data;
  switch (node.type) {
    case "input":
      for (const f of (d.fields as { key?: string; label?: string }[] | undefined) ?? [])
        add(f.key, f.label);
      break;
    case "llm":
      add("text", "AI 답");
      for (const [k, v] of Object.entries(propsOf(d.output_schema)))
        add(k, v.title ?? v.description);
      break;
    case "parameter_extractor":
      for (const p of (d.parameters as { name?: string; description?: string }[] | undefined) ?? [])
        add(p.name, p.description);
      break;
    case "set_fields":
      for (const f of (d.fields as { key?: string }[] | undefined) ?? []) add(f.key);
      break;
    case "variable_assigner":
      for (const k of Object.keys((d.variables as Record<string, unknown> | undefined) ?? {}))
        add(k);
      break;
    case "output":
      return [];
    default:
      break;
  }
  for (const [k, v] of Object.entries(propsOf(spec?.output_schema)))
    add(k, v.title ?? v.description);
  // 실패해도 이어 가게 해 둔 단계는 오류 내용을 낸다
  if (d._on_error === "branch" || d._on_error === "default") add("error", "오류 내용");
  return [...out.entries()].map(([key, label]) => ({ key, label }));
}

/** 지금 단계에서 끌어올 수 있는 값 묶음(앞 단계들 + 흐름 값 + 대화 값) */
export function valueGroups(
  nodes: RefNode[],
  edges: RefEdge[],
  specs: RefSpec[],
  currentId: string,
  flowVariables: Record<string, unknown> = {},
): ValueGroup[] {
  const ups = upstreamIds(currentId, edges);
  const specOf = new Map(specs.map((s) => [s.type, s]));
  const groups: ValueGroup[] = [];
  const used = new Set<string>();
  // 화면 순서와 비슷하게: 그래프에 적힌 순서
  for (const n of nodes) {
    if (!ups.has(n.id)) continue;
    const spec = specOf.get(n.type);
    const base = String(n.data.label || spec?.label || n.id);
    let group = base;
    let i = 2;
    while (used.has(group)) group = `${base} (${i++})`;
    used.add(group);
    const items = nodeOutputs(n, spec).map((o) => ({
      expr: `${n.id}.${o.key}`,
      label: `${group} › ${o.label}`,
      group,
      item: o.label,
    }));
    if (items.length) groups.push({ id: n.id, label: group, items });
  }
  const conv = new Map<string, string>();
  for (const n of nodes) {
    if (n.type !== "variable_assigner") continue;
    for (const k of Object.keys((n.data.variables as Record<string, unknown> | undefined) ?? {}))
      conv.set(k, k);
  }
  if (conv.size) {
    groups.push({
      id: "conv",
      label: "대화 값",
      items: [...conv.keys()].map((k) => ({
        expr: `conv.${k}`,
        label: `대화 값 › ${k}`,
        group: "대화 값",
        item: k,
      })),
    });
  }
  const vars = Object.keys(flowVariables);
  if (vars.length) {
    groups.push({
      id: "vars",
      label: "흐름 값",
      items: vars.map((k) => ({
        expr: `vars.${k}`,
        label: `흐름 값 › ${k}`,
        group: "흐름 값",
        item: k,
      })),
    });
  }
  return groups;
}

export function flatOptions(groups: ValueGroup[]): ValueOption[] {
  return groups.flatMap((g) => g.items);
}

/** 저장 형식 → 보통 모드 표시. 아는 값만 «이름»으로 바꾸고 나머지 {{ }}는 그대로 둔다. */
export function toDisplay(raw: string, options: ValueOption[]): string {
  const byExpr = new Map(options.map((o) => [o.expr, o.label]));
  return raw.replace(REF, (whole, inner: string) => {
    const label = byExpr.get(inner.trim());
    return label ? `«${label}»` : whole;
  });
}

/** 보통 모드 표시 → 저장 형식. 모르는 «…»는 글자 그대로 둔다. */
export function toRaw(display: string, options: ValueOption[]): string {
  const byLabel = new Map(options.map((o) => [o.label, o.expr]));
  return display.replace(CHIP, (whole, label: string) => {
    const expr = byLabel.get(label);
    return expr ? `{{${expr}}}` : whole;
  });
}

/** 글 속 {{ }} 참조 목록(아는 것은 이름까지) */
export function refsIn(
  raw: string,
  options: ValueOption[],
): { expr: string; label: string | null }[] {
  const byExpr = new Map(options.map((o) => [o.expr, o.label]));
  const out: { expr: string; label: string | null }[] = [];
  const seen = new Set<string>();
  for (const m of raw.matchAll(REF)) {
    const expr = (m[1] ?? "").trim();
    if (!expr || seen.has(expr)) continue;
    seen.add(expr);
    out.push({ expr, label: byExpr.get(expr) ?? null });
  }
  return out;
}

/** 특정 참조를 글에서 모두 지운다 */
export function removeRef(raw: string, expr: string): string {
  return raw.replace(REF, (whole, inner: string) => (inner.trim() === expr ? "" : whole));
}

/** 커서 위치(start~end)에 끼워 넣고 새 커서 위치를 돌려준다 */
export function insertAt(
  text: string,
  start: number,
  end: number,
  insertion: string,
): { text: string; cursor: number } {
  const s = Math.max(0, Math.min(start, text.length));
  const e = Math.max(s, Math.min(end, text.length));
  return { text: text.slice(0, s) + insertion + text.slice(e), cursor: s + insertion.length };
}

/** 고급 모드 자동완성: 커서 앞이 '{{검색어'면 {start, query}, 아니면 null */
export function autocompleteAt(
  text: string,
  cursor: number,
): { start: number; query: string } | null {
  const before = text.slice(0, cursor);
  const open = before.lastIndexOf("{{");
  if (open < 0) return null;
  const inside = before.slice(open + 2);
  if (inside.includes("}}") || inside.includes("\n") || inside.length > 60) return null;
  return { start: open, query: inside.trim() };
}

/** 자동완성 후보(표현식·이름 모두로 찾음) */
export function filterOptions(options: ValueOption[], query: string, limit = 8): ValueOption[] {
  const q = query.toLowerCase();
  if (!q) return options.slice(0, limit);
  return options
    .filter((o) => o.expr.toLowerCase().includes(q) || o.label.toLowerCase().includes(q))
    .slice(0, limit);
}

/** 자동완성 선택: '{{검색어'를 '{{표현식}}'으로 바꾼다 */
export function completeAt(
  text: string,
  start: number,
  cursor: number,
  expr: string,
): { text: string; cursor: number } {
  const after = text.slice(cursor);
  const closes = after.startsWith("}}") ? 2 : 0;
  return insertAt(text, start, cursor + closes, `{{${expr}}}`);
}

/** 값 끌어오기 버튼을 달지 않는 칸(이름·종류 고르기처럼 값을 넣을 일이 없는 칸) */
const SKIP = new Set([
  "label",
  "provider",
  "model",
  "method",
  "key",
  "id",
  "type",
  "name",
  "language",
  "operation",
  "unit",
  "timezone",
  "connector",
  "action",
  "credential_id",
  "kb_id",
  "table_id",
  "app_id",
  "else",
]);

export function wantsPicker(widgetId: string): boolean {
  const leaf = widgetId.split("_").pop() ?? "";
  return !SKIP.has(leaf) && !/^\d+$/.test(leaf);
}
