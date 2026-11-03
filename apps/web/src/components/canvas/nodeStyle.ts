import {
  BookOpen,
  Code2,
  Flag,
  GitBranch,
  Globe,
  Keyboard,
  Plug,
  Sparkles,
  UserCheck,
  type LucideIcon,
} from "lucide-react";

export const TYPE_ICON: Record<string, LucideIcon> = {
  input: Keyboard,
  output: Flag,
  llm: Sparkles,
  condition: GitBranch,
  http: Globe,
  code: Code2,
  knowledge_search: BookOpen,
  connector: Plug,
  approval: UserCheck,
};

/** 카테고리별 색(아이콘 타일·왼쪽 띠) */
export const CATEGORY_TONE: Record<string, { tile: string; bar: string }> = {
  기본: { tile: "bg-slate-100 text-slate-600", bar: "bg-slate-400" },
  AI: { tile: "bg-violet-100 text-violet-600", bar: "bg-violet-500" },
  흐름: { tile: "bg-amber-100 text-amber-700", bar: "bg-amber-500" },
  연동: { tile: "bg-sky-100 text-sky-600", bar: "bg-sky-500" },
  고급: { tile: "bg-emerald-100 text-emerald-700", bar: "bg-emerald-500" },
  마켓: { tile: "bg-pink-100 text-pink-600", bar: "bg-pink-500" },
};

const DEFAULT_TONE = { tile: "bg-slate-100 text-slate-600", bar: "bg-slate-400" };

export function toneOf(category?: string) {
  return CATEGORY_TONE[category ?? ""] ?? DEFAULT_TONE;
}
