import { useIsDark } from "@/store/theme";
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, type DragEvent } from "react";
import { NodeView, type GenioFlowNode } from "@/components/canvas/NodeView";
import { DRAG_TYPE } from "@/components/canvas/NodePalette";
import { defaultData } from "@/components/canvas/nodeUtils";
import type { NodeType } from "@/lib/api/types";
import { useCanvas } from "@/store/canvas";

const nodeTypes = { genio: NodeView };
// 글자가 읽히는 정도(0.7배) 아래로는 줄이지 않는다. 흐름이 길면 옆으로 끌어서 본다.
const FIT_OPTIONS = { padding: 0.15, maxZoom: 1, minZoom: 0.7 };

function Inner({ specs, readOnly }: { specs: NodeType[]; readOnly?: boolean }) {
  const graph = useCanvas((s) => s.graph);
  const selectedId = useCanvas((s) => s.selectedId);
  const highlights = useCanvas((s) => s.highlights);
  const nodeErrors = useCanvas((s) => s.nodeErrors);
  const steps = useCanvas((s) => s.steps);
  const { screenToFlowPosition, fitView, getNodes, getNodesBounds, getViewport, setViewport } =
    useReactFlow();

  const dark = useIsDark();
  const specMap = useMemo(() => new Map(specs.map((s) => [s.type, s])), [specs]);

  // fitView 속성은 첫 렌더에만 적용된다. 흐름을 불러오거나 빌더가 노드를 더하고 빼면
  // 화면에 다 보이도록 다시 맞춘다(노드를 끌어 옮길 때는 맞추지 않음).
  const nodeIdsKey = graph.nodes.map((n) => n.id).join(",");
  useEffect(() => {
    if (!nodeIdsKey) return;
    const t = window.setTimeout(() => {
      void fitView(FIT_OPTIONS).then(() => {
        // 최소 배율에 걸려 다 못 보여 줄 때는 흐름의 시작(왼쪽)이 보이게 맞춘다
        const vp = getViewport();
        if (vp.zoom > FIT_OPTIONS.minZoom + 0.001) return;
        const bounds = getNodesBounds(getNodes());
        void setViewport({ x: 32 - bounds.x * vp.zoom, y: vp.y, zoom: vp.zoom });
      });
    }, 60);
    return () => window.clearTimeout(t);
  }, [nodeIdsKey, fitView, getNodes, getNodesBounds, getViewport, setViewport]);

  const nodes: GenioFlowNode[] = useMemo(
    () =>
      graph.nodes.map((n) => ({
        id: n.id,
        type: "genio" as const,
        position: n.position,
        selected: n.id === selectedId,
        data: {
          node: n,
          spec: specMap.get(n.type),
          errors: nodeErrors[n.id],
          highlighted: Boolean(highlights[n.id]),
          step: steps[n.id],
        },
      })),
    [graph.nodes, selectedId, specMap, nodeErrors, highlights, steps],
  );

  const edges: Edge[] = useMemo(
    () =>
      graph.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle ?? null,
        targetHandle: e.targetHandle ?? null,
        label: e.sourceHandle ?? undefined,
        animated: steps[e.source]?.status === "succeeded" && Boolean(steps[e.target]),
      })),
    [graph.edges, steps],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange<GenioFlowNode>[]) => {
      const st = useCanvas.getState();
      for (const c of changes) {
        if (c.type === "position" && c.position && !readOnly) st.moveNode(c.id, c.position);
        else if (c.type === "remove" && !readOnly) st.removeNode(c.id);
        else if (c.type === "select" && c.selected) st.select(c.id);
      }
    },
    [readOnly],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      if (readOnly) return;
      for (const c of changes) if (c.type === "remove") useCanvas.getState().removeEdge(c.id);
    },
    [readOnly],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      if (readOnly || !c.source || !c.target) return;
      useCanvas.getState().connect({
        source: c.source,
        target: c.target,
        sourceHandle: c.sourceHandle ?? undefined,
      });
    },
    [readOnly],
  );

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    const type = e.dataTransfer.getData(DRAG_TYPE);
    if (!type || readOnly) return;
    const position = screenToFlowPosition({ x: e.clientX, y: e.clientY });
    useCanvas.getState().addNode(type, position, defaultData(specMap.get(type)));
  };

  return (
    <ReactFlow
      colorMode={dark ? "dark" : "light"}
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      onPaneClick={() => useCanvas.getState().select(null)}
      onDrop={onDrop}
      onDragOver={(e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
      }}
      nodesConnectable={!readOnly}
      deleteKeyCode={readOnly ? null : ["Delete", "Backspace"]}
      fitView
      fitViewOptions={FIT_OPTIONS}
      minZoom={0.2}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={16} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

export function FlowCanvas({ specs, readOnly }: { specs: NodeType[]; readOnly?: boolean }) {
  return (
    <ReactFlowProvider>
      <Inner specs={specs} readOnly={readOnly} />
    </ReactFlowProvider>
  );
}
