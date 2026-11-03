// v0.6 버전 비교: 두 버전(또는 작업본) 사이에 더한·뺀·바뀐 단계와 선
import { ArrowRight, Minus, Pencil, Plus } from "lucide-react";
import type { ReactNode } from "react";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Select } from "@/components/ui/input";
import { useVersionDiff, type DiffNode } from "@/lib/api/versions";

function NodeList({
  title,
  items,
  tone,
  icon,
}: {
  title: string;
  items: DiffNode[];
  tone: string;
  icon: ReactNode;
}) {
  if (!items.length) return null;
  return (
    <div>
      <p className="mb-1 text-xs font-semibold text-slate-500">{title}</p>
      <ul className="space-y-1.5">
        {items.map((n) => (
          <li key={n.id} className={`rounded-lg px-3 py-2 text-sm ${tone}`}>
            <div className="flex items-center gap-1.5 font-medium">
              {icon}
              {n.label}
              <span className="text-[11px] font-normal opacity-70">({n.type})</span>
            </div>
            {n.fields && n.fields.length > 0 && (
              <ul className="mt-1.5 space-y-1">
                {n.fields.map((f) => (
                  <li key={f.key} className="text-xs">
                    <span className="font-semibold">{f.name}</span>
                    <div className="mt-0.5 grid gap-1 sm:grid-cols-[1fr_auto_1fr] sm:items-start">
                      <code className="break-all rounded bg-red-50 px-1.5 py-0.5 text-red-700 line-through decoration-red-300">
                        {f.before}
                      </code>
                      <ArrowRight className="hidden h-3.5 w-3.5 text-slate-400 sm:block" />
                      <code className="break-all rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-800">
                        {f.after}
                      </code>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function VersionDiffView({
  appId,
  versions,
  from,
  to,
  onChange,
  onClose,
}: {
  appId: string;
  versions: number[];
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
  onClose: () => void;
}) {
  const diff = useVersionDiff(appId, from, to);
  const options = [
    ...versions.map((v) => ({ value: String(v), label: `버전 ${v}` })),
    { value: "draft", label: "지금 작업본" },
  ];
  const d = diff.data;
  return (
    <div
      className="space-y-3 border-t border-slate-100 px-4 py-3 sm:px-5"
      data-testid="version-diff"
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">버전 비교</span>
        <Select
          aria-label="비교 기준"
          className="w-auto"
          value={from}
          onChange={(e) => onChange(e.target.value, to)}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
        <ArrowRight className="h-4 w-4 text-slate-400" />
        <Select
          aria-label="비교 대상"
          className="w-auto"
          value={to}
          onChange={(e) => onChange(from, e.target.value)}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
        <button type="button" className="ml-auto text-xs text-slate-500" onClick={onClose}>
          닫기
        </button>
      </div>
      {diff.isLoading && <Loading />}
      <ErrorBox error={diff.error} />
      {d && (
        <div className="space-y-3">
          <ul className="list-disc space-y-0.5 rounded-lg bg-slate-50 py-2 pl-7 pr-3 text-sm text-slate-700">
            {d.summary.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          <NodeList
            title="추가한 단계"
            items={d.nodes_added}
            tone="bg-emerald-50 text-emerald-900"
            icon={<Plus className="h-3.5 w-3.5" />}
          />
          <NodeList
            title="지운 단계"
            items={d.nodes_removed}
            tone="bg-red-50 text-red-900"
            icon={<Minus className="h-3.5 w-3.5" />}
          />
          <NodeList
            title="설정을 바꾼 단계"
            items={d.nodes_changed}
            tone="bg-amber-50 text-amber-900"
            icon={<Pencil className="h-3.5 w-3.5" />}
          />
          {(d.edges_added.length > 0 || d.edges_removed.length > 0) && (
            <div>
              <p className="mb-1 text-xs font-semibold text-slate-500">연결선</p>
              <ul className="space-y-0.5 text-sm">
                {d.edges_added.map((e) => (
                  <li key={`+${e}`} className="text-emerald-700">
                    + {e}
                  </li>
                ))}
                {d.edges_removed.map((e) => (
                  <li key={`-${e}`} className="text-red-700">
                    − {e}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
