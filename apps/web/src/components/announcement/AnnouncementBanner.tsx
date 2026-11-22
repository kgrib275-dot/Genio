import { AlertTriangle, Info, Wrench } from "lucide-react";
import { useAnnouncement, type Announcement } from "@/lib/api/announcement";
import { cn } from "@/lib/cn";

const STYLE = {
  info: "bg-indigo-50 text-indigo-900 border-indigo-200",
  warn: "bg-amber-50 text-amber-900 border-amber-200",
  maintenance: "bg-red-50 text-red-900 border-red-200",
} as const;

/** 서비스 전체 공지(점검·장애 안내). 없으면 아무것도 그리지 않는다. */
export function AnnouncementBanner({ value }: { value?: Announcement }) {
  const q = useAnnouncement(!value);
  const a = value ?? q.data;
  if (!a?.active) return null;
  const Icon = a.level === "maintenance" ? Wrench : a.level === "warn" ? AlertTriangle : Info;
  return (
    <div
      role="status"
      data-testid="announcement"
      className={cn("flex items-start gap-2 border-b px-4 py-2 text-sm", STYLE[a.level])}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <p className="min-w-0 flex-1 whitespace-pre-wrap">{a.message}</p>
    </div>
  );
}
