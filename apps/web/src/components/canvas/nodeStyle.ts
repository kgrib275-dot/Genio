import {
  Bot,
  Braces,
  FileCode,
  FileDown,
  ImagePlus,
  FileText,
  ListFilter,
  ListTree,
  Merge,
  RefreshCw,
  Repeat,
  Variable,
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
  question_classifier: ListTree,
  parameter_extractor: Braces,
  template: FileCode,
  variable_aggregator: Merge,
  list_operator: ListFilter,
  iteration: Repeat,
  loop: RefreshCw,
  document_extractor: FileText,
  variable_assigner: Variable,
  agent: Bot,
  // v0.9
  image_generate: ImagePlus,
  file_export: FileDown,
};

/** 카테고리별 색(아이콘 타일·왼쪽 띠) */
export const CATEGORY_TONE: Record<string, { tile: string; bar: string }> = {
  기본: { tile: "bg-slate-100 text-slate-600", bar: "bg-slate-400" },
  AI: { tile: "bg-violet-100 text-violet-600", bar: "bg-violet-500" },
  흐름: { tile: "bg-amber-100 text-amber-700", bar: "bg-amber-500" },
  연동: { tile: "bg-sky-100 text-sky-600", bar: "bg-sky-500" },
  고급: { tile: "bg-emerald-100 text-emerald-700", bar: "bg-emerald-500" },
  마켓: { tile: "bg-pink-100 text-pink-600", bar: "bg-pink-500" },
  변환: { tile: "bg-teal-100 text-teal-700", bar: "bg-teal-500" },
  반복: { tile: "bg-orange-100 text-orange-700", bar: "bg-orange-500" },
  데이터: { tile: "bg-cyan-100 text-cyan-700", bar: "bg-cyan-500" },
};

const DEFAULT_TONE = { tile: "bg-slate-100 text-slate-600", bar: "bg-slate-400" };

export function toneOf(category?: string) {
  return CATEGORY_TONE[category ?? ""] ?? DEFAULT_TONE;
}
