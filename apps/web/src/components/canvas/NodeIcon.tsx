import { Puzzle } from "lucide-react";
import { TYPE_ICON, toneOf } from "@/components/canvas/nodeStyle";

export function NodeIcon({
  type,
  category,
  size = "md",
}: {
  type: string;
  category?: string;
  size?: "sm" | "md";
}) {
  const Icon = TYPE_ICON[type] ?? Puzzle;
  const dims = size === "sm" ? "h-7 w-7" : "h-8 w-8";
  return (
    <span
      className={`inline-flex ${dims} shrink-0 items-center justify-center rounded-lg ${toneOf(category).tile}`}
    >
      <Icon className="h-4 w-4" />
    </span>
  );
}
