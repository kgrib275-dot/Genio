// 같이 이 앱을 보고 있는 사람들(v0.9): 이름 동그라미와 '○○님이 고치는 중' 안내.
import { editingHint } from "@/lib/presenceUi";
import { useCollab } from "@/store/collab";

const SHOW = 4;

function initial(name: string): string {
  return name.trim().slice(0, 1) || "?";
}

export function PresenceBar() {
  const users = useCollab((s) => s.users);
  const me = useCollab((s) => s.me);
  const others = users.filter((u) => u.user_id !== me);
  if (others.length === 0) return null;
  const shown = others.slice(0, SHOW);
  const hint = editingHint(others);
  return (
    <div className="flex items-center gap-2" data-testid="presence-bar">
      <ul className="flex -space-x-1.5" aria-label="같이 보고 있는 사람">
        {shown.map((u) => (
          <li
            key={u.user_id}
            title={`${u.name} · ${u.editing ? "고치는 중" : u.can_edit ? "보는 중" : "보기만 하는 중"}`}
            className="inline-flex h-7 w-7 items-center justify-center rounded-full border-2 border-white text-[11px] font-bold text-white shadow-sm"
            style={{ backgroundColor: u.color }}
          >
            {initial(u.name)}
          </li>
        ))}
        {others.length > SHOW && (
          <li className="inline-flex h-7 w-7 items-center justify-center rounded-full border-2 border-white bg-slate-300 text-[11px] font-bold text-slate-700">
            +{others.length - SHOW}
          </li>
        )}
      </ul>
      {hint && (
        <span className="hidden items-center gap-1 text-xs text-slate-500 md:flex" role="status">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" />
          {hint}
        </span>
      )}
    </div>
  );
}
