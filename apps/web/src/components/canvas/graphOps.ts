// 캔버스 편집 도우미(순수 함수): 복사·붙여넣기, 끄기, 되돌리기 기록, 자동 정렬, 메모.
import dagre from "@dagrejs/dagre";
import type { Graph, GraphEdge, GraphNode, GraphNote, NoteColor } from "@/lib/api/types";

// ---------------- 복사·붙여넣기 ----------------
export interface Clip {
  nodes: GraphNode[];
  /** 복사한 블록끼리 이어진 연결만 */
  edges: GraphEdge[];
}

/** 고른 블록과 그 사이 연결을 복사한다. */
export function copySelection(graph: Graph, ids: string[]): Clip | null {
  const set = new Set(ids);
  const nodes = graph.nodes.filter((n) => set.has(n.id));
  if (nodes.length === 0) return null;
  const edges = graph.edges.filter((e) => set.has(e.source) && set.has(e.target));
  return structuredCloneSafe({ nodes, edges });
}

function structuredCloneSafe<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

function maxNum(ids: string[], prefix: string): number {
  let max = 0;
  const re = new RegExp(`^${prefix}(\\d+)$`);
  for (const id of ids) {
    const m = re.exec(id);
    if (m) max = Math.max(max, Number(m[1]));
  }
  return max;
}

/** 템플릿 안의 {{옛id.값}} 참조를 새 id로 바꾼다(복사한 블록끼리만). */
export function remapRefs(value: unknown, map: Map<string, string>): unknown {
  if (typeof value === "string") {
    return value.replace(/\{\{(\s*)([A-Za-z_][A-Za-z0-9_]*)(?=[.\s}|])/g, (all, sp, id) => {
      const to = map.get(id as string);
      return to ? `{{${sp as string}${to}` : all;
    });
  }
  if (Array.isArray(value)) return value.map((v) => remapRefs(v, map));
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, remapRefs(v, map)]),
    );
  return value;
}

export interface PasteResult {
  graph: Graph;
  newIds: string[];
  /** 시작 블록처럼 하나만 있어야 해서 뺀 개수 */
  skipped: number;
}

/** 복사한 블록을 새 id로 붙여 넣는다. 시작(입력) 블록은 하나만 둘 수 있어 뺀다. */
export function pasteClip(graph: Graph, clip: Clip, offset = { x: 40, y: 40 }): PasteResult {
  const hasInput = graph.nodes.some((n) => n.type === "input");
  const usable = clip.nodes.filter((n) => !(n.type === "input" && hasInput));
  const skipped = clip.nodes.length - usable.length;
  let nextN = maxNum(
    graph.nodes.map((n) => n.id),
    "n",
  );
  let nextE = maxNum(
    graph.edges.map((e) => e.id),
    "e",
  );
  const map = new Map<string, string>();
  for (const n of usable) map.set(n.id, `n${++nextN}`);
  const nodes: GraphNode[] = usable.map((n) => ({
    ...n,
    id: map.get(n.id) as string,
    position: { x: n.position.x + offset.x, y: n.position.y + offset.y },
    data: remapRefs(n.data, map) as Record<string, unknown>,
  }));
  const edges: GraphEdge[] = clip.edges
    .filter((e) => map.has(e.source) && map.has(e.target))
    .map((e) => ({
      ...e,
      id: `e${++nextE}`,
      source: map.get(e.source) as string,
      target: map.get(e.target) as string,
    }));
  return {
    graph: { ...graph, nodes: [...graph.nodes, ...nodes], edges: [...graph.edges, ...edges] },
    newIds: nodes.map((n) => n.id),
    skipped,
  };
}

// ---------------- 끄기·켜기 ----------------
/** 고른 블록을 끄거나 켠다. 하나라도 켜져 있으면 모두 끄고, 모두 꺼져 있으면 모두 켠다. */
export function toggleDisabled(graph: Graph, ids: string[]): Graph {
  const set = new Set(ids);
  const targets = graph.nodes.filter((n) => set.has(n.id));
  if (targets.length === 0) return graph;
  const turnOff = targets.some((n) => !n.disabled);
  return {
    ...graph,
    nodes: graph.nodes.map((n) => {
      if (!set.has(n.id)) return n;
      if (turnOff) return { ...n, disabled: true };
      const { disabled: _drop, ...rest } = n;
      void _drop;
      return rest;
    }),
  };
}

// ---------------- 되돌리기 기록 ----------------
export const HISTORY_LIMIT = 50;

export interface History {
  past: Graph[];
  future: Graph[];
}

export const emptyHistory = (): History => ({ past: [], future: [] });

/** 바뀌기 전 그래프를 기록한다(새 편집이 생기면 '다시 하기'는 비운다). */
export function record(h: History, before: Graph, limit = HISTORY_LIMIT): History {
  const past = [...h.past, before];
  return { past: past.length > limit ? past.slice(past.length - limit) : past, future: [] };
}

export function undo(h: History, current: Graph): { history: History; graph: Graph } | null {
  const prev = h.past[h.past.length - 1];
  if (!prev) return null;
  return {
    history: { past: h.past.slice(0, -1), future: [current, ...h.future] },
    graph: prev,
  };
}

export function redo(h: History, current: Graph): { history: History; graph: Graph } | null {
  const next = h.future[0];
  if (!next) return null;
  return {
    history: { past: [...h.past, current], future: h.future.slice(1) },
    graph: next,
  };
}

// ---------------- 자동 정렬 ----------------
const NODE_W = 240;

function nodeHeight(n: GraphNode): number {
  const d = n.data;
  const branches =
    n.type === "condition"
      ? ((d.cases as unknown[] | undefined)?.length ?? 0) + 1
      : n.type === "question_classifier"
        ? ((d.classes as unknown[] | undefined)?.length ?? 0)
        : 0;
  return 84 + branches * 24 + (d._on_error === "branch" ? 24 : 0);
}

/** 왼쪽에서 오른쪽으로 흐르게 블록 위치를 다시 잡는다. */
export function autoLayout(graph: Graph): Graph {
  if (graph.nodes.length === 0) return graph;
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 40, ranksep: 90, marginx: 40, marginy: 40 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of graph.nodes) g.setNode(n.id, { width: NODE_W, height: nodeHeight(n) });
  for (const e of graph.edges)
    if (graph.nodes.some((n) => n.id === e.source) && graph.nodes.some((n) => n.id === e.target))
      g.setEdge(e.source, e.target);
  dagre.layout(g);
  return {
    ...graph,
    nodes: graph.nodes.map((n) => {
      const p = g.node(n.id) as { x: number; y: number } | undefined;
      if (!p) return n;
      return {
        ...n,
        position: { x: Math.round(p.x - NODE_W / 2), y: Math.round(p.y - nodeHeight(n) / 2) },
      };
    }),
  };
}

// ---------------- 메모 ----------------
export const NOTE_COLORS: NoteColor[] = ["yellow", "blue", "green", "pink", "gray"];

export function nextNoteId(graph: Graph): string {
  return `m${
    maxNum(
      (graph.notes ?? []).map((m) => m.id),
      "m",
    ) + 1
  }`;
}

export function addNote(graph: Graph, position: { x: number; y: number }): [Graph, string] {
  const id = nextNoteId(graph);
  const note: GraphNote = { id, text: "", position, width: 220, height: 140, color: "yellow" };
  return [{ ...graph, notes: [...(graph.notes ?? []), note] }, id];
}

export function updateNote(graph: Graph, id: string, patch: Partial<GraphNote>): Graph {
  return {
    ...graph,
    notes: (graph.notes ?? []).map((m) => (m.id === id ? { ...m, ...patch } : m)),
  };
}

export function removeNote(graph: Graph, id: string): Graph {
  const notes = (graph.notes ?? []).filter((m) => m.id !== id);
  const { notes: _old, ...rest } = graph;
  void _old;
  return notes.length ? { ...rest, notes } : rest;
}
