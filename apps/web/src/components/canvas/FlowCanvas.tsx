import { useIsDark } from "@/store/theme";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Copy, ClipboardPaste, Layers, Power, Settings2, StickyNote, Trash2 } from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import { CanvasToolbar } from "@/components/canvas/CanvasToolbar";
import { NodeView, type GenioFlowNode } from "@/components/canvas/NodeView";
import { fanCounts } from "@/components/canvas/nodeUtils";
import { NoteView, type NoteFlowNode } from "@/components/canvas/NoteView";
import { copySelection, type Clip } from "@/components/canvas/graphOps";
import { DRAG_TYPE } from "@/components/canvas/NodePalette";
import { SnippetSaveDialog } from "@/components/canvas/SnippetDialogs";
import { registerViewportCenter } from "@/components/canvas/viewportBridge";
import { defaultData } from "@/components/canvas/nodeUtils";
import { toast } from "@/components/ui/toast-store";
import type { NodeType } from "@/lib/api/types";
import { useCanvas } from "@/store/canvas";

const nodeTypes = { genio: NodeView, note: NoteView };
// 글자가 읽히는 정도(0.7배) 아래로는 줄이지 않는다. 흐름이 길면 옆으로 끌어서 본다.
const FIT_OPTIONS = { padding: 0.15, maxZoom: 1, minZoom: 0.7 };
const NOTE_PREFIX = "note:";
const MINIMAP_KEY = "genio.canvas.minimap";

type FlowNode = GenioFlowNode | NoteFlowNode;

function readMinimap(): boolean {
  try {
    return window.localStorage.getItem(MINIMAP_KEY) === "1";
  } catch {
    return false;
  }
}

/** 입력칸·코드 편집기에 글을 치는 중이면 캔버스 단축키를 쓰지 않는다. */
function typingInField(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  return Boolean(el.closest?.(".monaco-editor"));
}

interface Menu {
  x: number;
  y: number;
  /** 단계 위에서 열었으면 단계 id, 빈 곳이면 null */
  nodeId: string | null;
  flow: { x: number; y: number };
}

function MenuItem({
  onClick,
  icon,
  children,
  danger,
  hint,
}: {
  onClick: () => void;
  icon: ReactNode;
  children: ReactNode;
  danger?: boolean;
  hint?: string;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] hover:bg-slate-100 ${danger ? "text-red-600" : "text-slate-700"}`}
    >
      {icon}
      <span className="flex-1">{children}</span>
      {hint && <span className="text-[11px] text-slate-400">{hint}</span>}
    </button>
  );
}

function Inner({ specs, readOnly }: { specs: NodeType[]; readOnly?: boolean }) {
  const graph = useCanvas((s) => s.graph);
  const selectedId = useCanvas((s) => s.selectedId);
  const selectedIds = useCanvas((s) => s.selectedIds);
  const highlights = useCanvas((s) => s.highlights);
  const nodeErrors = useCanvas((s) => s.nodeErrors);
  const steps = useCanvas((s) => s.steps);
  const canUndo = useCanvas((s) => s.history.past.length > 0);
  const canRedo = useCanvas((s) => s.history.future.length > 0);
  const [selNotes, setSelNotes] = useState<string[]>([]);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [snippetClip, setSnippetClip] = useState<Clip | null>(null);
  const [minimap, setMinimap] = useState(readMinimap);
  const wrapRef = useRef<HTMLDivElement>(null);
  const { screenToFlowPosition, fitView, getNodes, getNodesBounds, getViewport, setViewport } =
    useReactFlow();

  // 단계 추가 패널(캔버스 밖)이 스니펫을 '지금 보이는 화면 한가운데'에 놓을 수 있게 알려 둔다
  useEffect(() => {
    registerViewportCenter(() => {
      const rect = wrapRef.current?.getBoundingClientRect();
      return rect
        ? screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 })
        : { x: 200, y: 160 };
    });
    return () => registerViewportCenter(null);
  }, [screenToFlowPosition]);

  const dark = useIsDark();
  const specMap = useMemo(() => new Map(specs.map((s) => [s.type, s])), [specs]);

  // fitView 속성은 첫 렌더에만 적용된다. 흐름을 불러오거나 빌더가 단계를 더하고 빼면
  // 화면에 다 보이도록 다시 맞춘다(단계를 끌어 옮길 때는 맞추지 않음).
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

  const selectedSet = useMemo(
    () => new Set([...selectedIds, ...(selectedId ? [selectedId] : [])]),
    [selectedIds, selectedId],
  );

  const nodes: FlowNode[] = useMemo(
    () => [
      // 메모는 단계 뒤에 깔린다
      ...(graph.notes ?? []).map((m): NoteFlowNode => ({
        id: NOTE_PREFIX + m.id,
        type: "note",
        position: m.position,
        width: m.width,
        height: m.height,
        zIndex: -1,
        selected: selNotes.includes(m.id),
        data: { note: m, readOnly },
      })),
      ...graph.nodes.map((n): GenioFlowNode => ({
        id: n.id,
        type: "genio",
        position: n.position,
        selected: selectedSet.has(n.id),
        data: {
          node: n,
          spec: specMap.get(n.type),
          errors: nodeErrors[n.id],
          highlighted: Boolean(highlights[n.id]),
          step: steps[n.id],
          ...fanCounts(graph.edges, n.id),
        },
      })),
    ],
    [
      graph.nodes,
      graph.edges,
      graph.notes,
      selectedSet,
      selNotes,
      specMap,
      nodeErrors,
      highlights,
      steps,
      readOnly,
    ],
  );

  const disabledIds = useMemo(
    () => new Set(graph.nodes.filter((n) => n.disabled).map((n) => n.id)),
    [graph.nodes],
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
        style:
          disabledIds.has(e.source) || disabledIds.has(e.target)
            ? { strokeDasharray: "5 4", opacity: 0.6 }
            : undefined,
      })),
    [graph.edges, steps, disabledIds],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange<FlowNode>[]) => {
      const st = useCanvas.getState();
      let blocks: Set<string> | null = null;
      let notes: Set<string> | null = null;
      for (const c of changes) {
        const isNote = "id" in c && c.id.startsWith(NOTE_PREFIX);
        const noteId = isNote ? c.id.slice(NOTE_PREFIX.length) : "";
        if (c.type === "position" && c.position && !readOnly) {
          if (isNote) st.updateNote(noteId, { position: c.position });
          else st.moveNode(c.id, c.position);
        } else if (c.type === "remove" && !readOnly) {
          if (isNote) st.removeNote(noteId);
          else st.removeNode(c.id);
        } else if (c.type === "select") {
          if (isNote) {
            notes ??= new Set(selNotes);
            if (c.selected) notes.add(noteId);
            else notes.delete(noteId);
          } else {
            blocks ??= new Set(useCanvas.getState().selectedIds);
            if (c.selected) blocks.add(c.id);
            else blocks.delete(c.id);
          }
        }
      }
      if (blocks) st.setSelection([...blocks]);
      if (notes) setSelNotes([...notes]);
    },
    [readOnly, selNotes],
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
      if (c.source.startsWith(NOTE_PREFIX) || c.target.startsWith(NOTE_PREFIX)) return;
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

  // ---------- 동작(도구 막대·메뉴·단축키가 함께 씀) ----------
  const reportPaste = (r: { pasted: number; skipped: number }) => {
    if (r.skipped)
      toast.info(
        r.pasted
          ? "시작 단계는 하나만 둘 수 있어 빼고 붙였어요."
          : "시작 단계는 하나만 둘 수 있어 붙이지 않았어요.",
      );
  };
  const actions = {
    copy: () => {
      const n = useCanvas.getState().copy();
      if (n) toast.success(`단계 ${n}개를 복사했어요.`);
    },
    paste: () => reportPaste(useCanvas.getState().paste()),
    duplicate: () => reportPaste(useCanvas.getState().duplicate()),
    toggle: () => useCanvas.getState().toggleDisabledSelected(),
    remove: () => useCanvas.getState().deleteSelected(),
    saveSnippet: () => {
      const { graph: g, selectedIds: ids, selectedId: one } = useCanvas.getState();
      const clip = copySelection(g, ids.length ? ids : one ? [one] : []);
      if (clip) setSnippetClip(clip);
    },
    undo: () => useCanvas.getState().undo(),
    redo: () => useCanvas.getState().redo(),
    arrange: () => {
      useCanvas.getState().autoArrange();
      window.setTimeout(() => void fitView(FIT_OPTIONS), 50);
    },
    addNote: (at?: { x: number; y: number }) => {
      let pos = at;
      if (!pos) {
        const rect = wrapRef.current?.getBoundingClientRect();
        pos = rect
          ? screenToFlowPosition({ x: rect.left + rect.width / 2 - 110, y: rect.top + 80 })
          : { x: 40, y: 40 };
      }
      const id = useCanvas.getState().addNote({ x: Math.round(pos.x), y: Math.round(pos.y) });
      setSelNotes([id]);
    },
  };
  const actionsRef = useRef(actions);
  actionsRef.current = actions;

  // ---------- 단축키 ----------
  useEffect(() => {
    if (readOnly) return;
    const onKey = (e: KeyboardEvent) => {
      if (typingInField(e.target)) return;
      // 캔버스가 화면에 없으면(모바일 다른 탭) 쓰지 않는다
      if (!wrapRef.current || wrapRef.current.offsetParent === null) return;
      const a = actionsRef.current;
      const mod = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();
      if (mod && key === "z" && !e.shiftKey) {
        e.preventDefault();
        a.undo();
      } else if (mod && ((key === "z" && e.shiftKey) || key === "y")) {
        e.preventDefault();
        a.redo();
      } else if (mod && key === "c") {
        if (window.getSelection()?.toString()) return;
        if (!useCanvas.getState().selectedIds.length && !useCanvas.getState().selectedId) return;
        e.preventDefault();
        a.copy();
      } else if (mod && key === "v") {
        if (!useCanvas.getState().clipboard) return;
        e.preventDefault();
        a.paste();
      } else if (mod && key === "d") {
        e.preventDefault();
        a.duplicate();
      } else if (!mod && !e.altKey && key === "d") {
        e.preventDefault();
        a.toggle();
      } else if (key === "escape") {
        setMenu(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [readOnly]);

  // ---------- 오른쪽 클릭 메뉴 ----------
  const openMenu = (e: ReactMouseEvent, nodeId: string | null) => {
    if (readOnly) return;
    e.preventDefault();
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    if (nodeId && !useCanvas.getState().selectedIds.includes(nodeId)) {
      useCanvas.getState().setSelection([nodeId]);
    }
    setMenu({
      x: Math.min(e.clientX - rect.left, rect.width - 200),
      y: Math.min(e.clientY - rect.top, rect.height - 230),
      nodeId,
      flow: screenToFlowPosition({ x: e.clientX, y: e.clientY }),
    });
  };
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [menu]);

  const selCount = selectedIds.length || (selectedId ? 1 : 0);
  const selNodes = graph.nodes.filter((n) => selectedSet.has(n.id));
  const allDisabled = selNodes.length > 0 && selNodes.every((n) => n.disabled);
  const menuNode = menu?.nodeId ? graph.nodes.find((n) => n.id === menu.nodeId) : undefined;

  return (
    <div ref={wrapRef} className="relative h-full w-full">
      <ReactFlow<FlowNode, Edge>
        colorMode={dark ? "dark" : "light"}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onPaneClick={() => {
          useCanvas.getState().setSelection([]);
          setSelNotes([]);
          setMenu(null);
        }}
        onNodeContextMenu={(e, n: Node) => openMenu(e, n.id.startsWith(NOTE_PREFIX) ? null : n.id)}
        onPaneContextMenu={(e) => openMenu(e as ReactMouseEvent, null)}
        onDrop={onDrop}
        onDragOver={(e) => {
          e.preventDefault();
          e.dataTransfer.dropEffect = "move";
        }}
        nodesConnectable={!readOnly}
        nodesDraggable={!readOnly}
        deleteKeyCode={readOnly ? null : ["Delete", "Backspace"]}
        multiSelectionKeyCode={["Meta", "Control"]}
        fitView
        fitViewOptions={FIT_OPTIONS}
        minZoom={0.2}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={16} />
        <Controls showInteractive={false} />
        {minimap && (
          <MiniMap
            pannable
            zoomable
            ariaLabel="미니맵"
            className="!hidden sm:!block"
            nodeColor={(n) =>
              n.type === "note"
                ? "rgba(251, 191, 36, 0.5)"
                : disabledIds.has(n.id)
                  ? "rgba(148, 163, 184, 0.5)"
                  : "rgb(99, 102, 241)"
            }
          />
        )}
      </ReactFlow>
      <CanvasToolbar
        readOnly={readOnly}
        canUndo={canUndo}
        canRedo={canRedo}
        hasSelection={selCount > 0}
        allDisabled={allDisabled}
        minimap={minimap}
        onAddNote={() => actions.addNote()}
        onUndo={actions.undo}
        onRedo={actions.redo}
        onToggleDisabled={actions.toggle}
        onDuplicate={actions.duplicate}
        onSaveSnippet={actions.saveSnippet}
        onArrange={actions.arrange}
        onToggleMinimap={() =>
          setMinimap((v) => {
            try {
              window.localStorage.setItem(MINIMAP_KEY, v ? "0" : "1");
            } catch {
              // 기억하지 못해도 동작에는 문제없다
            }
            return !v;
          })
        }
      />
      <SnippetSaveDialog clip={snippetClip} onClose={() => setSnippetClip(null)} />
      {menu && (
        <div
          role="menu"
          aria-label={menuNode ? "단계 메뉴" : "캔버스 메뉴"}
          className="absolute z-20 w-48 rounded-xl border border-slate-200 bg-white p-1 shadow-lift"
          style={{ left: Math.max(4, menu.x), top: Math.max(4, menu.y) }}
          onClick={(e) => e.stopPropagation()}
        >
          {menuNode ? (
            <>
              <MenuItem
                icon={<Settings2 className="h-3.5 w-3.5" />}
                onClick={() => {
                  useCanvas.getState().setSelection([menuNode.id]);
                  setMenu(null);
                }}
              >
                설정 열기
              </MenuItem>
              <MenuItem
                icon={<Power className="h-3.5 w-3.5" />}
                hint="D"
                onClick={() => {
                  actions.toggle();
                  setMenu(null);
                }}
              >
                {allDisabled ? "켜기" : "끄기(건너뛰기)"}
              </MenuItem>
              <MenuItem
                icon={<Copy className="h-3.5 w-3.5" />}
                onClick={() => {
                  actions.duplicate();
                  setMenu(null);
                }}
              >
                복제
              </MenuItem>
              <MenuItem
                icon={<Copy className="h-3.5 w-3.5" />}
                onClick={() => {
                  actions.copy();
                  setMenu(null);
                }}
              >
                복사
              </MenuItem>
              <MenuItem
                icon={<Layers className="h-3.5 w-3.5" />}
                onClick={() => {
                  actions.saveSnippet();
                  setMenu(null);
                }}
              >
                스니펫으로 저장{selCount > 1 ? ` (${selCount}개)` : ""}
              </MenuItem>
              <div className="my-1 h-px bg-slate-100" />
              <MenuItem
                danger
                icon={<Trash2 className="h-3.5 w-3.5" />}
                hint="Delete"
                onClick={() => {
                  actions.remove();
                  setMenu(null);
                }}
              >
                지우기{selCount > 1 ? ` (${selCount}개)` : ""}
              </MenuItem>
            </>
          ) : (
            <>
              <MenuItem
                icon={<StickyNote className="h-3.5 w-3.5" />}
                onClick={() => {
                  actions.addNote(menu.flow);
                  setMenu(null);
                }}
              >
                여기에 메모 추가
              </MenuItem>
              <MenuItem
                icon={<ClipboardPaste className="h-3.5 w-3.5" />}
                onClick={() => {
                  actions.paste();
                  setMenu(null);
                }}
              >
                붙여넣기
              </MenuItem>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function FlowCanvas({ specs, readOnly }: { specs: NodeType[]; readOnly?: boolean }) {
  return (
    <ReactFlowProvider>
      <Inner specs={specs} readOnly={readOnly} />
    </ReactFlowProvider>
  );
}
