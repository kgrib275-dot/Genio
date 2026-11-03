// 캔버스 메모(n8n 스티커 메모). 실행과 상관없이 설명을 적어 둔다.
import { NodeResizer, type Node, type NodeProps } from "@xyflow/react";
import { Trash2 } from "lucide-react";
import { NOTE_COLORS } from "@/components/canvas/graphOps";
import type { GraphNote, NoteColor } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { useCanvas } from "@/store/canvas";

export interface NoteNodeData extends Record<string, unknown> {
  note: GraphNote;
  readOnly?: boolean;
}

export type NoteFlowNode = Node<NoteNodeData, "note">;

const TONE: Record<NoteColor, string> = {
  yellow: "bg-amber-100 border-amber-300",
  blue: "bg-sky-100 border-sky-300",
  green: "bg-emerald-100 border-emerald-300",
  pink: "bg-pink-100 border-pink-300",
  gray: "bg-slate-100 border-slate-300",
};

const DOT: Record<NoteColor, string> = {
  yellow: "bg-amber-400",
  blue: "bg-sky-400",
  green: "bg-emerald-400",
  pink: "bg-pink-400",
  gray: "bg-slate-400",
};

const COLOR_LABEL: Record<NoteColor, string> = {
  yellow: "노랑",
  blue: "파랑",
  green: "초록",
  pink: "분홍",
  gray: "회색",
};

export function NoteView({ data, selected }: NodeProps<NoteFlowNode>) {
  const { note, readOnly } = data;
  const update = (patch: Partial<GraphNote>) => useCanvas.getState().updateNote(note.id, patch);
  return (
    <div
      data-testid={`note-${note.id}`}
      className={cn(
        "flex h-full w-full flex-col rounded-lg border shadow-sm",
        TONE[note.color] ?? TONE.yellow,
        selected && "ring-2 ring-indigo-400/60",
      )}
      style={{ width: note.width, height: note.height }}
    >
      {!readOnly && (
        <NodeResizer
          isVisible={selected}
          minWidth={80}
          minHeight={60}
          lineClassName="!border-indigo-400"
          handleClassName="!h-2.5 !w-2.5 !rounded-sm !border-indigo-400 !bg-white"
          onResizeEnd={(_, p) =>
            update({
              width: Math.round(p.width),
              height: Math.round(p.height),
              position: { x: Math.round(p.x), y: Math.round(p.y) },
            })
          }
        />
      )}
      {selected && !readOnly && (
        <div className="nodrag flex items-center gap-1 border-b border-black/5 px-2 py-1">
          {NOTE_COLORS.map((c) => (
            <button
              key={c}
              type="button"
              aria-label={`메모 색: ${COLOR_LABEL[c]}`}
              title={COLOR_LABEL[c]}
              onClick={() => update({ color: c })}
              className={cn(
                "h-3.5 w-3.5 rounded-full",
                DOT[c],
                note.color === c && "ring-2 ring-slate-700/40 ring-offset-1",
              )}
            />
          ))}
          <button
            type="button"
            aria-label="메모 지우기"
            title="메모 지우기"
            onClick={() => useCanvas.getState().removeNote(note.id)}
            className="ml-auto rounded p-0.5 text-slate-500 hover:bg-black/5 hover:text-red-600"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
      <textarea
        aria-label="메모 내용"
        placeholder={readOnly ? "" : "메모를 적어 두세요"}
        readOnly={readOnly}
        value={note.text}
        onChange={(e) => update({ text: e.target.value })}
        className="nodrag nowheel min-h-0 w-full flex-1 resize-none bg-transparent px-2.5 py-2 text-[13px] leading-relaxed text-slate-800 placeholder:text-slate-400 focus:outline-none"
      />
    </div>
  );
}
