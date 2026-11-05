import { Layers, Search } from "lucide-react";
import { useState } from "react";
import { NodeIcon } from "@/components/canvas/NodeIcon";
import { SnippetList } from "@/components/canvas/SnippetList";
import { useSnippets, type SnippetFull } from "@/lib/api/snippets";
import type { NodeType } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { useSession } from "@/store/session";

export const DRAG_TYPE = "application/genio-node";

type Tab = "nodes" | "snippets";

export function NodePalette({
  types,
  onAdd,
  onInsertSnippet,
}: {
  types: NodeType[];
  onAdd: (type: NodeType) => void;
  /** 주면 '스니펫' 탭이 생긴다(저장해 둔 단계 묶음을 끼워 넣기) */
  onInsertSnippet?: (snippet: SnippetFull) => void;
}) {
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<Tab>("nodes");
  const ws = useSession((s) => s.workspaceId);
  const snippets = useSnippets(onInsertSnippet ? ws : "");
  const filtered = types.filter(
    (t) => !q || t.label.includes(q) || t.description.includes(q) || t.type.includes(q),
  );
  const groups = new Map<string, NodeType[]>();
  for (const t of filtered) groups.set(t.category, [...(groups.get(t.category) ?? []), t]);
  return (
    <div className="flex max-h-[70vh] flex-col">
      {onInsertSnippet && (
        <div
          role="tablist"
          aria-label="추가할 것"
          className="flex gap-1 border-b border-slate-100 p-2"
        >
          {(
            [
              ["nodes", "단계", null],
              ["snippets", "스니펫", snippets.data?.length ?? null],
            ] as const
          ).map(([key, label, count]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={cn(
                "inline-flex flex-1 items-center justify-center gap-1 rounded-md py-1 text-[13px]",
                tab === key
                  ? "bg-indigo-50 font-semibold text-indigo-700"
                  : "text-slate-500 hover:bg-slate-100",
              )}
            >
              {key === "snippets" && <Layers className="h-3.5 w-3.5" aria-hidden />}
              {label}
              {count !== null && count > 0 && (
                <span className="text-[11px] font-normal text-slate-400">{count}</span>
              )}
            </button>
          ))}
        </div>
      )}
      {tab === "snippets" && onInsertSnippet ? (
        <div className="overflow-y-auto">
          <SnippetList onInsert={onInsertSnippet} />
        </div>
      ) : (
        <>
          <div className="border-b border-slate-100 p-2">
            <div className="flex items-center gap-2 rounded-lg bg-slate-100 px-2.5 py-1.5">
              <Search className="h-3.5 w-3.5 text-slate-400" />
              <input
                autoFocus
                aria-label="단계 검색"
                placeholder="단계 검색"
                className="w-full bg-transparent text-sm placeholder:text-slate-400 focus:outline-none"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </div>
            <p className="mt-1.5 px-1 text-[11px] text-slate-400">
              눌러서 추가하거나 캔버스로 끌어 놓으세요.
            </p>
          </div>
          <div className="space-y-3 overflow-y-auto p-2">
            {[...groups.entries()].map(([cat, list]) => (
              <div key={cat}>
                <p className="mb-1 px-1 text-[11px] font-semibold text-slate-400">{cat}</p>
                <div className="space-y-0.5">
                  {list.map((t) => (
                    <button
                      key={t.type}
                      type="button"
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData(DRAG_TYPE, t.type);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      onClick={() => onAdd(t)}
                      className="flex w-full items-start gap-2.5 rounded-lg px-2 py-1.5 text-left hover:bg-slate-100"
                    >
                      <NodeIcon type={t.type} category={t.category} size="sm" />
                      <span className="min-w-0">
                        <span className="block text-[13px] font-medium text-slate-800">
                          {t.label}
                          {t.source === "market" && (
                            <span className="ml-1 text-[10px] font-normal text-pink-500">마켓</span>
                          )}
                        </span>
                        <span className="line-clamp-2 block text-[11px] leading-snug text-slate-500">
                          {t.description}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
            {filtered.length === 0 && (
              <p className="p-3 text-center text-xs text-slate-400">찾는 단계가 없어요.</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
