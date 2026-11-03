// 캔버스와 빌더 챗이 함께 쓰는 그래프 상태(설계서 §9).
import { create } from "zustand";
import type { Graph, GraphEdge, GraphError, GraphNode, PatchOp, RunStep } from "@/lib/api/types";

export const emptyGraph = (): Graph => ({ version: 1, nodes: [], edges: [], variables: {} });

/** 빌더 patch 연산을 그래프에 적용한다. 원본은 바꾸지 않는다. */
export function applyPatch(graph: Graph, ops: PatchOp[]): Graph {
  let nodes = [...graph.nodes];
  let edges = [...graph.edges];
  for (const op of ops) {
    switch (op.op) {
      case "add_node":
        nodes = [...nodes.filter((n) => n.id !== op.node.id), op.node];
        break;
      case "update_node":
        nodes = nodes.map((n) => (n.id === op.id ? { ...n, data: { ...n.data, ...op.data } } : n));
        break;
      case "remove_node":
        nodes = nodes.filter((n) => n.id !== op.id);
        edges = edges.filter((e) => e.source !== op.id && e.target !== op.id);
        break;
      case "add_edge":
        edges = [...edges.filter((e) => e.id !== op.edge.id), op.edge];
        break;
      case "remove_edge":
        edges = edges.filter((e) => e.id !== op.id);
        break;
    }
  }
  return { ...graph, nodes, edges };
}

/** patch가 건드린 노드 id 목록(하이라이트용). */
export function touchedNodeIds(ops: PatchOp[]): string[] {
  const ids = new Set<string>();
  for (const op of ops) {
    if (op.op === "add_node") ids.add(op.node.id);
    else if (op.op === "update_node") ids.add(op.id);
    else if (op.op === "add_edge") {
      ids.add(op.edge.source);
      ids.add(op.edge.target);
    }
  }
  return [...ids];
}

export function nextNodeId(graph: Graph): string {
  let max = 0;
  for (const n of graph.nodes) {
    const m = /^n(\d+)$/.exec(n.id);
    if (m) max = Math.max(max, Number(m[1]));
  }
  return `n${max + 1}`;
}

function nextEdgeId(graph: Graph): string {
  let max = 0;
  for (const e of graph.edges) {
    const m = /^e(\d+)$/.exec(e.id);
    if (m) max = Math.max(max, Number(m[1]));
  }
  return `e${max + 1}`;
}

export type GraphErrors = Record<string, string[]>;

export function groupErrors(errors: GraphError[]): { byNode: GraphErrors; general: string[] } {
  const byNode: GraphErrors = {};
  const general: string[] = [];
  for (const e of errors) {
    if (e.node_id) (byNode[e.node_id] ??= []).push(e.message);
    else general.push(e.message);
  }
  return { byNode, general };
}

interface CanvasState {
  appId: string;
  graph: Graph;
  dirty: boolean;
  /** 사용자 편집 횟수. 늘어나면 작업본 저장을 예약한다. */
  editSeq: number;
  selectedId: string | null;
  highlights: Record<string, number>;
  nodeErrors: GraphErrors;
  generalErrors: string[];
  steps: Record<string, RunStep>;

  load: (appId: string, graph: Graph) => void;
  /** 서버(빌더)에서 받은 그래프로 바꾼다. 사용자 편집이 아니므로 저장 예약을 하지 않는다. */
  replaceFromServer: (graph: Graph, highlight?: string[]) => void;
  markSaved: () => void;
  edit: (fn: (g: Graph) => Graph) => void;
  addNode: (
    type: string,
    position: { x: number; y: number },
    data?: Record<string, unknown>,
  ) => string;
  updateNodeData: (id: string, data: Record<string, unknown>) => void;
  moveNode: (id: string, position: { x: number; y: number }) => void;
  removeNode: (id: string) => void;
  connect: (edge: Omit<GraphEdge, "id">) => void;
  removeEdge: (id: string) => void;
  select: (id: string | null) => void;
  setErrors: (errors: GraphError[]) => void;
  clearHighlight: (id: string) => void;
  setStep: (step: RunStep) => void;
  resetSteps: () => void;
}

export const useCanvas = create<CanvasState>((set, get) => ({
  appId: "",
  graph: emptyGraph(),
  dirty: false,
  editSeq: 0,
  selectedId: null,
  highlights: {},
  nodeErrors: {},
  generalErrors: [],
  steps: {},

  load: (appId, graph) =>
    set({
      appId,
      graph,
      dirty: false,
      editSeq: 0,
      selectedId: null,
      highlights: {},
      nodeErrors: {},
      generalErrors: [],
      steps: {},
    }),

  replaceFromServer: (graph, highlight = []) => {
    const now = Date.now();
    const highlights = { ...get().highlights };
    for (const id of highlight) highlights[id] = now;
    set({ graph, highlights, dirty: false });
    for (const id of highlight) {
      setTimeout(() => get().clearHighlight(id), 2000);
    }
  },

  markSaved: () => set({ dirty: false }),

  edit: (fn) => set((s) => ({ graph: fn(s.graph), dirty: true, editSeq: s.editSeq + 1 })),

  addNode: (type, position, data = {}) => {
    const id = nextNodeId(get().graph);
    const node: GraphNode = { id, type, position, data: { label: data.label ?? type, ...data } };
    get().edit((g) => applyPatch(g, [{ op: "add_node", node }]));
    set({ selectedId: id });
    return id;
  },

  updateNodeData: (id, data) =>
    get().edit((g) => ({
      ...g,
      nodes: g.nodes.map((n) => (n.id === id ? { ...n, data } : n)),
    })),

  moveNode: (id, position) =>
    get().edit((g) => ({
      ...g,
      nodes: g.nodes.map((n) => (n.id === id ? { ...n, position } : n)),
    })),

  removeNode: (id) => {
    get().edit((g) => applyPatch(g, [{ op: "remove_node", id }]));
    if (get().selectedId === id) set({ selectedId: null });
  },

  connect: (edge) =>
    get().edit((g) => {
      const exists = g.edges.some(
        (e) =>
          e.source === edge.source &&
          e.target === edge.target &&
          (e.sourceHandle ?? null) === (edge.sourceHandle ?? null),
      );
      if (exists || edge.source === edge.target) return g;
      return applyPatch(g, [{ op: "add_edge", edge: { ...edge, id: nextEdgeId(g) } }]);
    }),

  removeEdge: (id) => get().edit((g) => applyPatch(g, [{ op: "remove_edge", id }])),

  select: (id) => set({ selectedId: id }),

  setErrors: (errors) => {
    const { byNode, general } = groupErrors(errors);
    set({ nodeErrors: byNode, generalErrors: general });
  },

  clearHighlight: (id) =>
    set((s) => ({
      highlights: Object.fromEntries(Object.entries(s.highlights).filter(([k]) => k !== id)),
    })),

  setStep: (step) => set((s) => ({ steps: { ...s.steps, [step.node_id]: step } })),
  resetSteps: () => set({ steps: {} }),
}));
