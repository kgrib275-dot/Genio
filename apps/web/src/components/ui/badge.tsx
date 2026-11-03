import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Tone = "gray" | "green" | "red" | "amber" | "blue" | "indigo";

const tones: Record<Tone, string> = {
  gray: "bg-slate-100 text-slate-700",
  green: "bg-emerald-100 text-emerald-800",
  red: "bg-red-100 text-red-800",
  amber: "bg-amber-100 text-amber-800",
  blue: "bg-sky-100 text-sky-800",
  indigo: "bg-indigo-100 text-indigo-800",
};

export function Badge({
  tone = "gray",
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

const STATUS: Record<string, { tone: Tone; label: string }> = {
  queued: { tone: "gray", label: "대기" },
  running: { tone: "blue", label: "실행 중" },
  succeeded: { tone: "green", label: "성공" },
  failed: { tone: "red", label: "실패" },
  waiting_approval: { tone: "amber", label: "승인 대기" },
  skipped: { tone: "gray", label: "건너뜀" },
  uploaded: { tone: "gray", label: "올림" },
  processing: { tone: "blue", label: "처리 중" },
  ready: { tone: "green", label: "준비됨" },
  draft: { tone: "gray", label: "작성 중" },
  published: { tone: "green", label: "배포됨" },
  installed: { tone: "green", label: "설치됨" },
  disabled: { tone: "gray", label: "꺼짐" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { tone: "gray" as Tone, label: status };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}
