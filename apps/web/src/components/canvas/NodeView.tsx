import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { StatusBadge } from "@/components/ui/badge";
import { NodeIcon } from "@/components/canvas/NodeIcon";
import { toneOf } from "@/components/canvas/nodeStyle";
import { branchHandles, hasFailHandle } from "@/components/canvas/nodeUtils";
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
    case "question_classifier":
      return ((d.classes as { name?: string }[] | undefined) ?? []).map((c) => c.name).join(" / ");
    case "parameter_extractor":
      return ((d.parameters as { name?: string }[] | undefined) ?? [])
        .map((p) => p.name)
        .join(", ");
    case "template":
      return String(d.template ?? "").slice(0, 60);
    case "variable_aggregator":
      return ((d.variables as string[] | undefined) ?? []).join(" · ").slice(0, 60);
    case "list_operator":
    case "iteration":
      return String(d.items ?? d.input ?? "").slice(0, 60);
    case "loop":
      return `최대 ${String(d.max_iterations ?? "?")}회`;
    case "document_extractor":
      return String(d.file ?? "").slice(0, 60);
    case "variable_assigner":
      return ((d.assignments as { variable?: string }[] | undefined) ?? [])
        .map((a) => a.variable)
        .join(", ");
    case "agent":
      return String(d.instruction ?? d.query ?? "").slice(0, 60);
    default:
      return "";
  }
}

export function NodeView({ data, selected }: NodeProps<GenioFlowNode>) {
  const { node, spec, errors, highlighted, step } = data;
  const handles = branchHandles(node.type, node.data);
  const isBranching = handles.length > 0 || node.type === "condition";
  const fail = hasFailHandle(node.data);
  const hasErrors = Boolean(errors && errors.length);
  const label = (node.data.label as string | undefined) || spec?.label || node.type;

  return (
    <div
      data-testid={`node-${node.id}`}
      className={cn(
        "relative w-60 overflow-hidden rounded-xl border bg-white text-left shadow-card transition-shadow hover:shadow-lift",
        hasErrors ? "border-red-400 ring-2 ring-red-200" : "border-slate-200",
        selected && !hasErrors && "border-indigo-400 ring-4 ring-indigo-500/15",
        highlighted && "genio-highlight",
      )}
    >
      <span className={cn("absolute inset-y-0 left-0 w-1", toneOf(spec?.category).bar)} />
      {node.type !== "input" && (
        <Handle
          type="target"
          position={Position.Left}
          className="!h-3 !w-3 !border-2 !border-white !bg-slate-400"
        />
      )}
      <div className="py-2.5 pl-4 pr-3">
        <div className="flex items-center gap-2.5">
          <NodeIcon type={node.type} category={spec?.category} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-semibold text-slate-900">{label}</p>
            <p className="truncate text-[11px] text-slate-400">{spec?.label ?? node.type}</p>
          </div>
          {step && <StatusBadge status={step.status} />}
        </div>
        {summary(node) && (
          <p className="mt-2 truncate rounded-md bg-slate-50 px-2 py-1 font-mono text-[11px] text-slate-500">
            {summary(node)}
          </p>
        )}
        {hasErrors && (
          <ul className="mt-2 space-y-0.5">
            {errors?.map((e, i) => (
              <li key={i} className="text-[11px] leading-snug text-red-600">
                {e}
              </li>
            ))}
          </ul>
        )}
        {handles.length > 0 && (
          <div className="mt-2 space-y-1">
            {handles.map((h) => (
              <div
                key={h.id}
                className="relative rounded-md bg-amber-50 px-2 py-0.5 text-right text-[11px] font-medium text-amber-800"
              >
                {h.label}
                <Handle
                  type="source"
                  id={h.id}
                  position={Position.Right}
                  className="!h-2.5 !w-2.5 !border-2 !border-white !bg-amber-500"
                  style={{ top: "50%", right: -14 }}
                />
              </div>
            ))}
          </div>
        )}
        {fail && (
          <div className="relative mt-1 rounded-md bg-red-50 px-2 py-0.5 text-right text-[11px] font-medium text-red-700">
            실패 시
            <Handle
              type="source"
              id="fail"
              position={Position.Right}
              className="!h-2.5 !w-2.5 !border-2 !border-white !bg-red-500"
              style={{ top: "50%", right: -14 }}
            />
          </div>
        )}
      </div>
      {!isBranching && node.type !== "output" && (
        <Handle
          type="source"
          position={Position.Right}
          className="!h-3 !w-3 !border-2 !border-white !bg-indigo-500"
        />
      )}
    </div>
  );
}
