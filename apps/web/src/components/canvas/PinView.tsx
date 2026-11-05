// 캔버스 빈 곳에 꽂은 댓글 핀(v0.9). 누르면 댓글 패널에서 그 스레드를 연다.
import type { Node, NodeProps } from "@xyflow/react";
import { MessageSquare } from "lucide-react";
import type { CommentThread } from "@/lib/api/collab";
import { useCollab } from "@/store/collab";

export interface PinNodeData extends Record<string, unknown> {
  thread: CommentThread;
}

export type PinFlowNode = Node<PinNodeData, "pin">;

export function PinView({ data }: NodeProps<PinFlowNode>) {
  const t = data.thread;
  const count = 1 + t.replies.length;
  return (
    <button
      type="button"
      data-testid={`pin-${t.id}`}
      aria-label={`댓글 핀 ${count}개: ${t.body.slice(0, 30)}`}
      title={`${t.author.name}: ${t.body.slice(0, 60)}`}
      onClick={(e) => {
        e.stopPropagation();
        useCollab.getState().focusThread(t.id);
      }}
      className="relative flex h-8 w-8 items-center justify-center rounded-full rounded-bl-none bg-indigo-600 text-white shadow-lift ring-2 ring-white hover:bg-indigo-500"
    >
      <MessageSquare className="h-4 w-4" />
      {count > 1 && (
        <span className="absolute -right-1 -top-1 min-w-4 rounded-full bg-amber-400 px-1 text-[10px] font-bold leading-4 text-slate-900">
          {count}
        </span>
      )}
    </button>
  );
}
