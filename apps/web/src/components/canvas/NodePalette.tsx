import type { NodeType } from "@/lib/api/types";

export const DRAG_TYPE = "application/genio-node";

export function NodePalette({
  types,
  onAdd,
}: {
  types: NodeType[];
  onAdd: (type: NodeType) => void;
}) {
  const groups = new Map<string, NodeType[]>();
  for (const t of types) groups.set(t.category, [...(groups.get(t.category) ?? []), t]);
  return (
    <div className="space-y-3 p-3">
      <p className="text-xs text-slate-500">끌어다 놓거나 눌러서 추가해요.</p>
      {[...groups.entries()].map(([cat, list]) => (
        <div key={cat}>
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            {cat}
          </p>
          <div className="space-y-1">
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
                title={t.description}
                className="w-full rounded border border-slate-200 bg-white px-2 py-1.5 text-left text-xs hover:border-indigo-300 hover:bg-indigo-50"
              >
                <span className="font-medium">{t.label}</span>
                {t.source === "market" && (
                  <span className="ml-1 text-[10px] text-indigo-500">마켓</span>
                )}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
