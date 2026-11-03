import { MessageSquare, Plus, Trash2, X } from "lucide-react";
import type { SessionEntry } from "@/lib/api/chat";
import { cn, timeAgo } from "@/lib/cn";

/** 이 브라우저에서 나눈 지난 대화 목록. 넓은 화면은 왼쪽 칸, 좁은 화면·위젯은 덮는 서랍. */
export function ChatHistory({
  sessions,
  activeId,
  overlay,
  onSelect,
  onNew,
  onRemove,
  onClose,
}: {
  sessions: SessionEntry[];
  activeId?: string;
  overlay: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRemove: (id: string) => void;
  onClose: () => void;
}) {
  const body = (
    <nav
      aria-label="지난 대화"
      className={cn(
        "flex h-full w-72 max-w-[85vw] flex-col border-r border-slate-200 bg-white",
        !overlay && "w-64",
      )}
    >
      <div className="flex items-center gap-2 border-b border-slate-100 p-2.5">
        <button
          type="button"
          onClick={onNew}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-[color:var(--chat-accent)] px-3 py-2 text-sm font-medium text-white hover:opacity-90"
        >
          <Plus className="h-4 w-4" /> 새 대화
        </button>
        <button
          type="button"
          onClick={onClose}
          aria-label="지난 대화 닫기"
          className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <p className="px-3 pb-1 pt-3 text-[11px] font-semibold text-slate-400">지난 대화</p>
      <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-1.5 pb-3">
        {sessions.length === 0 && (
          <li className="px-2 py-6 text-center text-xs text-slate-400">
            아직 지난 대화가 없어요.
            <br />이 브라우저에서 나눈 대화가 여기에 남아요.
          </li>
        )}
        {sessions.map((s) => (
          <li key={s.session_id} className="group relative">
            <button
              type="button"
              onClick={() => onSelect(s.session_id)}
              aria-current={s.session_id === activeId ? "true" : undefined}
              className={cn(
                "flex w-full items-start gap-2 rounded-lg px-2.5 py-2 pr-8 text-left text-sm",
                s.session_id === activeId
                  ? "bg-slate-100 font-medium text-slate-900"
                  : "text-slate-600 hover:bg-slate-50",
              )}
            >
              <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{s.title}</span>
                <span className="block text-[11px] font-normal text-slate-400">
                  {timeAgo(s.updated_at)}
                </span>
              </span>
            </button>
            <button
              type="button"
              onClick={() => onRemove(s.session_id)}
              aria-label={`'${s.title}' 목록에서 지우기`}
              title="목록에서 지우기"
              className="absolute right-1.5 top-2 rounded p-1 text-slate-300 opacity-100 hover:bg-slate-200 hover:text-red-600 sm:opacity-0 sm:group-hover:opacity-100 sm:focus:opacity-100"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
  if (!overlay) return body;
  return (
    <div className="absolute inset-0 z-30 flex">
      <div className="h-full animate-[genio-rise_.2s_ease-out]">{body}</div>
      <button
        type="button"
        aria-label="지난 대화 닫기"
        className="flex-1 bg-slate-900/30"
        onClick={onClose}
      />
    </div>
  );
}
