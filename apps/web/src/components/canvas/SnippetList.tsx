// 단계 추가 패널의 '스니펫' 탭: 저장해 둔 단계 묶음을 눌러 캔버스에 끼워 넣는다.
import { Layers, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { toast } from "@/components/ui/toast-store";
import {
  fetchSnippet,
  useDeleteSnippet,
  useSnippets,
  useUpdateSnippet,
  type Snippet,
  type SnippetFull,
} from "@/lib/api/snippets";
import { cn } from "@/lib/cn";
import { norm } from "@/lib/useListControls";
import { useSession } from "@/store/session";

export function SnippetList({ onInsert }: { onInsert: (s: SnippetFull) => void }) {
  const ws = useSession((s) => s.workspaceId);
  const list = useSnippets(ws);
  const update = useUpdateSnippet(ws);
  const del = useDeleteSnippet(ws);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);

  const items = (list.data ?? []).filter(
    (s) => !q || norm(`${s.name} ${s.description}`).includes(norm(q)),
  );

  async function insert(s: Snippet) {
    setBusy(s.id);
    try {
      onInsert(await fetchSnippet(ws, s.id));
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(null);
    }
  }

  if (list.isLoading) return <Loading />;
  if (list.error) return <ErrorBox error={list.error} />;
  if ((list.data ?? []).length === 0)
    return (
      <EmptyState
        compact
        icon={<Layers className="h-5 w-5" />}
        title="저장한 스니펫이 없어요"
        description="캔버스에서 단계를 고르고 도구 막대나 오른쪽 클릭 메뉴의 '스니펫으로 저장'을 눌러 보세요."
      />
    );
  return (
    <div className="space-y-2 p-2">
      <input
        aria-label="스니펫 검색"
        placeholder="스니펫 검색"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 text-sm placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
      />
      <ul className="space-y-1">
        {items.map((s) => (
          <li
            key={s.id}
            className={cn(
              "group rounded-lg border border-transparent px-2 py-1.5 hover:border-slate-200 hover:bg-slate-50",
              busy === s.id && "opacity-60",
            )}
          >
            {editing?.id === s.id ? (
              <form
                className="flex gap-1"
                onSubmit={(e) => {
                  e.preventDefault();
                  const name = editing.name.trim();
                  if (!name) return;
                  update.mutate(
                    { id: s.id, name },
                    {
                      onSuccess: () => setEditing(null),
                      onError: (err) => toast.error(err),
                    },
                  );
                }}
              >
                <input
                  autoFocus
                  aria-label="스니펫 이름"
                  value={editing.name}
                  maxLength={100}
                  onChange={(e) => setEditing({ id: s.id, name: e.target.value })}
                  onKeyDown={(e) => e.key === "Escape" && setEditing(null)}
                  className="h-8 min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                />
                <button
                  type="submit"
                  className="rounded-md bg-indigo-600 px-2 text-xs font-medium text-white hover:bg-indigo-500"
                >
                  저장
                </button>
              </form>
            ) : (
              <div className="flex items-start gap-1">
                <button
                  type="button"
                  onClick={() => void insert(s)}
                  className="min-w-0 flex-1 text-left"
                  title="눌러서 캔버스에 끼워 넣기"
                >
                  <span className="block truncate text-[13px] font-medium text-slate-800">
                    {s.name}
                  </span>
                  {s.description && (
                    <span className="line-clamp-2 block text-[11px] leading-snug text-slate-500">
                      {s.description}
                    </span>
                  )}
                  <span className="mt-0.5 block text-[11px] text-slate-400">
                    단계 {s.node_count}개
                    {s.reselect.length > 0 && (
                      <span className="text-amber-600"> · 다시 고를 칸 {s.reselect.length}곳</span>
                    )}
                    {s.outer_refs.length > 0 && (
                      <span className="text-amber-600"> · 바깥 값 {s.outer_refs.length}곳</span>
                    )}
                  </span>
                </button>
                <button
                  type="button"
                  aria-label={`${s.name} 이름 바꾸기`}
                  title="이름 바꾸기"
                  onClick={() => setEditing({ id: s.id, name: s.name })}
                  className="rounded p-1 text-slate-400 opacity-0 hover:bg-slate-100 hover:text-slate-700 focus:opacity-100 group-hover:opacity-100"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  aria-label={`${s.name} 지우기`}
                  title="지우기"
                  onClick={() => {
                    if (
                      window.confirm(
                        `'${s.name}' 스니펫을 지울까요? 이미 끼워 넣은 단계는 그대로예요.`,
                      )
                    )
                      del.mutate(s.id, { onError: (err) => toast.error(err) });
                  }}
                  className="rounded p-1 text-slate-400 opacity-0 hover:bg-red-50 hover:text-red-600 focus:opacity-100 group-hover:opacity-100"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
          </li>
        ))}
        {items.length === 0 && (
          <li className="p-3 text-center text-xs text-slate-400">찾는 스니펫이 없어요.</li>
        )}
      </ul>
    </div>
  );
}
