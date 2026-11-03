// 캔버스와 빌더 챗이 함께 쓰는 그래프 상태(설계서 §9).
import { create } from "zustand";
import {
  addNote as addNoteOp,
  autoLayout,
  copySelection,
  emptyHistory,
  pasteClip,
  record,
  redo as redoOp,
  removeNote as removeNoteOp,
  toggleDisabled,
  undo as undoOp,
  updateNote as updateNoteOp,
  type Clip,
  type History,
} from "@/components/canvas/graphOps";
import type {
  Graph,
  GraphEdge,
  GraphError,
  GraphNode,
  GraphNote,
  PatchOp,
  RunStep,
} from "@/lib/api/types";

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

/** patch가 건드린 단계 id 목록(하이라이트용). */
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
  /** 함께 고른 단계들(복사·끄기·삭제 대상). selectedId는 설정 패널에 여는 단계 하나. */
  selectedIds: string[];
  /** 되돌리기·다시 하기 기록 */
  history: History;
  /** 짧은 시간 안에 같은 종류로 이어지는 편집(끌어 옮기기 등)은 기록 한 번으로 묶는다 */
  lastRecord: { key: string; at: number } | null;
  clipboard: Clip | null;
  highlights: Record<string, number>;
  nodeErrors: GraphErrors;
  generalErrors: string[];
  steps: Record<string, RunStep>;

  load: (appId: string, graph: Graph) => void;
  /** 서버(빌더)에서 받은 그래프로 바꾼다. 사용자 편집이 아니므로 저장 예약을 하지 않는다. */
  replaceFromServer: (graph: Graph, highlight?: string[]) => void;
  markSaved: () => void;
  /** key가 같은 편집이 1초 안에 이어지면 되돌리기 기록을 하나로 묶는다 */
  edit: (fn: (g: Graph) => Graph, key?: string) => void;
  undo: () => void;
  redo: () => void;
  setSelection: (ids: string[]) => void;
  copy: () => number;
  paste: () => { pasted: number; skipped: number };
  duplicate: () => { pasted: number; skipped: number };
  toggleDisabledSelected: () => void;
  deleteSelected: () => void;
  autoArrange: () => void;
  addNote: (position: { x: number; y: number }) => string;
  updateNote: (id: string, patch: Partial<GraphNote>) => void;
  removeNote: (id: string) => void;
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
  selectedIds: [],
  history: emptyHistory(),
  lastRecord: null,
  clipboard: null,
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
      selectedIds: [],
      history: emptyHistory(),
      lastRecord: null,
      highlights: {},
      nodeErrors: {},
      generalErrors: [],
      steps: {},
    }),

  replaceFromServer: (graph, highlight = []) => {
    const now = Date.now();
    const highlights = { ...get().highlights };
    for (const id of highlight) highlights[id] = now;
    // 빌더가 바꾼 것도 되돌릴 수 있게 기록한다
    set((s) => ({
      graph,
      highlights,
      dirty: false,
      history: record(s.history, s.graph),
      lastRecord: null,
    }));
    for (const id of highlight) {
      setTimeout(() => get().clearHighlight(id), 2000);
    }
  },

  markSaved: () => set({ dirty: false }),

  edit: (fn, key) =>
    set((s) => {
      const next = fn(s.graph);
      if (next === s.graph) return {};
      const now = Date.now();
      const merge =
        key !== undefined &&
        s.lastRecord !== null &&
        s.lastRecord.key === key &&
        now - s.lastRecord.at < 1000;
      return {
        graph: next,
        dirty: true,
        editSeq: s.editSeq + 1,
        history: merge ? s.history : record(s.history, s.graph),
        lastRecord: key !== undefined ? { key, at: now } : null,
      };
    }),

  undo: () =>
    set((s) => {
      const r = undoOp(s.history, s.graph);
      if (!r) return {};
      return {
        graph: r.graph,
        history: r.history,
        lastRecord: null,
        dirty: true,
        editSeq: s.editSeq + 1,
        selectedId: r.graph.nodes.some((n) => n.id === s.selectedId) ? s.selectedId : null,
      };
    }),

  redo: () =>
    set((s) => {
      const r = redoOp(s.history, s.graph);
      if (!r) return {};
      return {
        graph: r.graph,
        history: r.history,
        lastRecord: null,
        dirty: true,
        editSeq: s.editSeq + 1,
        selectedId: r.graph.nodes.some((n) => n.id === s.selectedId) ? s.selectedId : null,
      };
    }),

  setSelection: (ids) =>
    set((s) => ({
      selectedIds: ids,
      selectedId:
        ids.length === 1
          ? (ids[0] ?? null)
          : ids.includes(s.selectedId ?? "")
            ? s.selectedId
            : null,
    })),

  copy: () => {
    const { graph, selectedIds, selectedId } = get();
    const ids = selectedIds.length ? selectedIds : selectedId ? [selectedId] : [];
    const clip = copySelection(graph, ids);
    if (clip) set({ clipboard: clip });
    return clip?.nodes.length ?? 0;
  },

  paste: () => {
    const clip = get().clipboard;
    if (!clip) return { pasted: 0, skipped: 0 };
    const r = pasteClip(get().graph, clip);
    if (r.newIds.length) {
      get().edit(() => r.graph);
      // 다음 붙여넣기는 조금 더 비켜서 놓이게 위치를 옮겨 둔다
      set({
        clipboard: {
          ...clip,
          nodes: clip.nodes.map((n) => ({
            ...n,
            position: { x: n.position.x + 40, y: n.position.y + 40 },
          })),
        },
        selectedIds: r.newIds,
        selectedId: r.newIds.length === 1 ? (r.newIds[0] ?? null) : null,
      });
    }
    return { pasted: r.newIds.length, skipped: r.skipped };
  },

  duplicate: () => {
    const { graph, selectedIds, selectedId } = get();
    const ids = selectedIds.length ? selectedIds : selectedId ? [selectedId] : [];
    const clip = copySelection(graph, ids);
    if (!clip) return { pasted: 0, skipped: 0 };
    const r = pasteClip(graph, clip);
    if (r.newIds.length) {
      get().edit(() => r.graph);
      set({
        selectedIds: r.newIds,
        selectedId: r.newIds.length === 1 ? (r.newIds[0] ?? null) : null,
      });
    }
    return { pasted: r.newIds.length, skipped: r.skipped };
  },

  toggleDisabledSelected: () => {
    const { selectedIds, selectedId } = get();
    const ids = selectedIds.length ? selectedIds : selectedId ? [selectedId] : [];
    if (ids.length) get().edit((g) => toggleDisabled(g, ids));
  },

  deleteSelected: () => {
    const { selectedIds, selectedId } = get();
    const ids = new Set(selectedIds.length ? selectedIds : selectedId ? [selectedId] : []);
    if (!ids.size) return;
    get().edit((g) =>
      applyPatch(
        g,
        [...ids].map((id) => ({ op: "remove_node" as const, id })),
      ),
    );
    set({ selectedIds: [], selectedId: null });
  },

  autoArrange: () => get().edit((g) => autoLayout(g)),

  addNote: (position) => {
    let id = "";
    get().edit((g) => {
      const [next, nid] = addNoteOp(g, position);
      id = nid;
      return next;
    });
    return id;
  },

  updateNote: (id, patch) =>
    get().edit(
      (g) => updateNoteOp(g, id, patch),
      `note:${id}:${Object.keys(patch).sort().join(",")}`,
    ),

  removeNote: (id) => get().edit((g) => removeNoteOp(g, id)),

  addNode: (type, position, data = {}) => {
    const id = nextNodeId(get().graph);
    const node: GraphNode = { id, type, position, data: { label: data.label ?? type, ...data } };
    get().edit((g) => applyPatch(g, [{ op: "add_node", node }]));
    set({ selectedId: id });
    return id;
  },

  updateNodeData: (id, data) =>
    get().edit(
      (g) => ({
        ...g,
        nodes: g.nodes.map((n) => (n.id === id ? { ...n, data } : n)),
      }),
      `data:${id}`,
    ),

  moveNode: (id, position) =>
    get().edit(
      (g) => ({
        ...g,
        nodes: g.nodes.map((n) => (n.id === id ? { ...n, position } : n)),
      }),
      "move",
    ),

  removeNode: (id) => {
    get().edit((g) => applyPatch(g, [{ op: "remove_node", id }]), "remove");
    set((s) => ({
      selectedId: s.selectedId === id ? null : s.selectedId,
      selectedIds: s.selectedIds.filter((x) => x !== id),
    }));
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

  select: (id) => set({ selectedId: id, selectedIds: id ? [id] : [] }),

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
