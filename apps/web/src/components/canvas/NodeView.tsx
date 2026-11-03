import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { StatusBadge } from "@/components/ui/badge";
import { conditionHandles } from "@/components/canvas/nodeUtils";
import type { GraphNode, NodeType, RunStep } from "@/lib/api/types";
import { cn } from "@/lib/cn";

export interface GenioNodeData extends Record<string, unknown> {
  node: GraphNode;
  spec?: NodeType;
  errors?: string[];
  highlighted?: boolean;
  step?: RunStep;
}

export type GenioFlowNode = Node<GenioNodeData, "genio">;

const CATEGORY_COLOR: Record<string, string> = {
  기본: "border-l-slate-500",
  AI: "border-l-violet-500",
  흐름: "border-l-amber-500",
  연동: "border-l-sky-500",
  고급: "border-l-emerald-600",
};

const TYPE_ICON: Record<string, string> = {
  input: "⌨️",
  output: "📤",
  llm: "✨",
  condition: "🔀",
  http: "🌐",
  code: "🧩",
  knowledge_search: "📚",
  connector: "🔌",
  approval: "✅",
};

function summary(node: GraphNode): string {
  const d = node.data;
  switch (node.type) {
    case "llm":
      return String(d.prompt ?? "").slice(0, 60);
    case "output":
      return String(d.template ?? "").slice(0, 60);
    case "http":
      return `${String(d.method ?? "GET")} ${String(d.url ?? "")}`.slice(0, 60);
    case "connector":
      return [d.connector, d.action].filter(Boolean).join(" · ");
    case "input":
      return ((d.fields as { key?: string }[] | undefined) ?? []).map((f) => f.key).join(", ");
    case "approval":
      return String(d.message ?? "").slice(0, 60);
    default:
      return "";
  }
}

export function NodeView({ data, selected }: NodeProps<GenioFlowNode>) {
  const { node, spec, errors, highlighted, step } = data;
  const isCondition = node.type === "condition";
  const handles = isCondition ? conditionHandles(node.data) : [];
  const hasErrors = Boolean(errors && errors.length);
  const label = (node.data.label as string | undefined) || spec?.label || node.type;

  return (
    <div
      data-testid={`node-${node.id}`}
      className={cn(
        "w-56 rounded-md border border-l-4 bg-white text-left shadow-sm transition-shadow",
        CATEGORY_COLOR[spec?.category ?? ""] ?? "border-l-slate-400",
        hasErrors ? "border-red-500 ring-2 ring-red-300" : "border-slate-200",
        selected && !hasErrors && "ring-2 ring-indigo-400",
        highlighted && "genio-highlight",
      )}
    >
      {node.type !== "input" && (
        <Handle type="target" position={Position.Left} className="!h-3 !w-3 !bg-slate-400" />
      )}
      <div className="px-3 py-2">
        <div className="flex items-center gap-1.5">
          <span aria-hidden>{TYPE_ICON[node.type] ?? "🔧"}</span>
          <span className="truncate text-sm font-semibold text-slate-900">{label}</span>
          {step && (
            <span className="ml-auto">
              <StatusBadge status={step.status} />
            </span>
          )}
        </div>
        <p className="mt-0.5 text-[11px] text-slate-400">
          {node.id} · {spec?.label ?? node.type}
        </p>
        {summary(node) && <p className="mt-1 truncate text-xs text-slate-600">{summary(node)}</p>}
        {hasErrors && (
          <ul className="mt-1 space-y-0.5">
            {errors?.map((e, i) => (
              <li key={i} className="text-[11px] leading-snug text-red-600">
                {e}
              </li>
            ))}
          </ul>
        )}
        {isCondition && (
          <div className="mt-2 space-y-1">
            {handles.map((h) => (
              <div key={h} className="relative pr-3 text-right text-[11px] text-amber-700">
                {h}
                <Handle
                  type="source"
                  id={h}
                  position={Position.Right}
                  className="!h-2.5 !w-2.5 !bg-amber-500"
                  style={{ top: "50%", right: -16 }}
                />
              </div>
            ))}
          </div>
        )}
      </div>
      {!isCondition && node.type !== "output" && (
        <Handle type="source" position={Position.Right} className="!h-3 !w-3 !bg-indigo-500" />
      )}
    </div>
  );
}
