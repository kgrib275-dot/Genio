// 동시 편집 충돌 해결(v0.9): '충돌 해결' 창이 쓰는 순수 함수들.
// 서버가 돌려준 합친 결과(merged, 충돌 항목은 상대 값)에 사용자가 고른 쪽을 반영해 저장할 흐름을 만든다.
import type { ConflictItem } from "@/lib/api/collab";

export type Side = "mine" | "theirs";
export type Choices = Record<string, Side>;

type Item = Record<string, unknown> & { id?: string; data?: Record<string, unknown> };
type GraphLike = {
  nodes?: Item[];
  edges?: Item[];
  notes?: Item[];
  variables?: Record<string, unknown>;
} & Record<string, unknown>;

export function conflictKey(c: Pick<ConflictItem, "kind" | "node_id" | "field">): string {
  return `${c.kind}:${c.node_id}:${c.field}`;
}

const FIELD_LABELS: Record<string, string> = {
  "*": "전체",
  type: "단계 종류",
  position: "자리",
  disabled: "켜기·끄기",
  "data.label": "이름",
  "data.prompt": "AI에게 줄 지시",
  "data.system": "역할 지시",
  "data.template": "글 틀",
  "data.url": "주소",
  "data.method": "방식",
  "data.headers": "헤더",
  "data.body": "보낼 내용",
  "data.cases": "조건",
  "data.else": "그 밖의 길",
  "data.fields": "입력 칸",
  "data.model": "모델",
  "data.provider": "AI 연결",
  "data.message": "안내 문구",
  "data.code": "코드",
  "data.kb_id": "지식베이스",
  "data.query": "검색어",
  text: "메모 글",
  color: "색",
};

/** 충돌 칸 이름을 업무 말로. */
export function fieldLabel(c: Pick<ConflictItem, "kind" | "field">): string {
  if (c.kind === "variable") return "값";
  if (c.kind === "edge") return "연결선";
  if (c.field === "*") return c.kind === "note" ? "메모 전체" : "단계 전체";
  return FIELD_LABELS[c.field] ?? (c.field.startsWith("data.") ? c.field.slice(5) : c.field);
}

const KIND_LABEL: Record<ConflictItem["kind"], string> = {
  node: "단계",
  edge: "연결선",
  note: "메모",
  variable: "값",
};

export function kindLabel(kind: ConflictItem["kind"]): string {
  return KIND_LABEL[kind];
}

/** 화면에 보일 값: JSON 대신 짧은 글. */
export function valueText(v: unknown, limit = 140): string {
  if (v === null || v === undefined) return "(없음·지움)";
  let t: string;
  if (typeof v === "string") t = v === "" ? "(빈 칸)" : v;
  else if (typeof v === "boolean") t = v ? "예" : "아니요";
  else if (typeof v === "number") t = String(v);
  else if (Array.isArray(v)) t = v.length ? `목록 ${v.length}개` : "(빈 목록)";
  else if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    const label =
      o.data && typeof o.data === "object" ? (o.data as Record<string, unknown>).label : undefined;
    t = typeof label === "string" && label ? `'${label}' 단계` : "항목";
  } else t = String(v);
  return t.length > limit ? `${t.slice(0, limit - 1)}…` : t;
}

/** 처음 상태: 모든 충돌을 상대 것으로(서버가 합쳐 준 그대로). */
export function defaultChoices(conflicts: ConflictItem[]): Choices {
  return Object.fromEntries(conflicts.map((c) => [conflictKey(c), "theirs" as Side]));
}

export function allChosen(conflicts: ConflictItem[], choices: Choices): boolean {
  return conflicts.every((c) => choices[conflictKey(c)] !== undefined);
}

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

function listOf(g: GraphLike, kind: "node" | "edge" | "note"): Item[] {
  const name = kind === "node" ? "nodes" : kind === "edge" ? "edges" : "notes";
  const cur = g[name] as Item[] | undefined;
  if (!cur) g[name] = [];
  return g[name] as Item[];
}

/** 사용자가 '내 것'을 고른 충돌만 합친 흐름에 되살린다. */
export function applyChoices(
  merged: unknown,
  conflicts: ConflictItem[],
  choices: Choices,
): GraphLike {
  const g = clone((merged ?? {}) as GraphLike);
  for (const c of conflicts) {
    if ((choices[conflictKey(c)] ?? "theirs") !== "mine") continue;
    if (c.kind === "variable") {
      const vars = (g.variables ??= {});
      if (c.mine === null || c.mine === undefined) Reflect.deleteProperty(vars, c.node_id);
      else vars[c.node_id] = clone(c.mine);
      continue;
    }
    const list = listOf(g, c.kind);
    const idx = list.findIndex((i) => i.id === c.node_id);
    if (c.field === "*") {
      if (c.mine === null || c.mine === undefined) {
        if (idx >= 0) list.splice(idx, 1);
      } else if (idx >= 0) list[idx] = clone(c.mine) as Item;
      else list.push(clone(c.mine) as Item);
      continue;
    }
    const item = list[idx];
    if (!item) continue;
    if (c.field.startsWith("data.")) {
      const data = (item.data ??= {});
      const key = c.field.slice(5);
      if (c.mine === null || c.mine === undefined) Reflect.deleteProperty(data, key);
      else data[key] = clone(c.mine);
    } else if (c.mine === null || c.mine === undefined) {
      Reflect.deleteProperty(item, c.field);
    } else {
      item[c.field] = clone(c.mine);
    }
  }
  // 없는 단계를 가리키는 연결선은 지운다
  const ids = new Set((g.nodes ?? []).map((n) => n.id));
  if (g.edges)
    g.edges = g.edges.filter((e) => ids.has(e.source as string) && ids.has(e.target as string));
  return g;
}

export interface ConflictGroup {
  id: string;
  kind: ConflictItem["kind"];
  label: string;
  items: ConflictItem[];
}

/** 단계(또는 메모·연결선·값)별로 묶어서 보여 준다. */
export function groupConflicts(conflicts: ConflictItem[]): ConflictGroup[] {
  const map = new Map<string, ConflictGroup>();
  for (const c of conflicts) {
    const id = `${c.kind}:${c.node_id}`;
    const g = map.get(id) ?? { id, kind: c.kind, label: c.label || c.node_id, items: [] };
    g.items.push(c);
    map.set(id, g);
  }
  return [...map.values()];
}

/** 바뀌었거나 새로 생긴 단계 id(남이 고친 단계를 캔버스에서 잠깐 반짝이게 한다). */
export function changedNodeIds(before: unknown, after: unknown): string[] {
  const prev = new Map(
    ((before as GraphLike)?.nodes ?? []).map((n) => [n.id as string, JSON.stringify(n)]),
  );
  const out: string[] = [];
  for (const n of (after as GraphLike)?.nodes ?? []) {
    const old = prev.get(n.id as string);
    if (old === undefined || old !== JSON.stringify(n)) out.push(n.id as string);
  }
  return out;
}

/** 두 흐름이 (자리 외에는) 같은지. 같은 내용이 알림으로 되돌아온 경우를 걸러 낸다. */
export function sameGraph(a: unknown, b: unknown): boolean {
  const norm = (g: unknown) => {
    const o = clone((g ?? {}) as GraphLike);
    const sortById = (l?: Item[]) =>
      l ? [...l].sort((x, y) => String(x.id).localeCompare(String(y.id))) : [];
    return JSON.stringify({
      nodes: sortById(o.nodes),
      edges: sortById(o.edges),
      notes: sortById(o.notes),
      variables: o.variables ?? {},
    });
  };
  return norm(a) === norm(b);
}
