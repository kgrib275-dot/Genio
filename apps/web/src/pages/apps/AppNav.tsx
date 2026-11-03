import { ChevronLeft, History, Rocket, Wand2 } from "lucide-react";
import type { ReactNode } from "react";
import { Link, NavLink } from "react-router-dom";
import { AppIcon } from "@/components/AppIcon";
import { cn } from "@/lib/cn";
import { canEdit, useSession } from "@/store/session";

export function AppNav({
  appId,
  title,
  icon,
  right,
}: {
  appId: string;
  title: string;
  icon?: string;
  right?: ReactNode;
}) {
  const role = useSession((s) => s.role);
  const tabs = [
    ...(canEdit(role) ? [{ to: `/apps/${appId}/builder`, label: "만들기", Icon: Wand2 }] : []),
    { to: `/apps/${appId}/runs`, label: "실행 기록", Icon: History },
    { to: `/apps/${appId}/settings`, label: "배포·설정", Icon: Rocket },
  ];
  return (
    <div className="flex h-14 shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-4">
      <Link
        to="/"
        title="내 앱으로"
        className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-900"
      >
        <ChevronLeft className="h-5 w-5" />
      </Link>
      <AppIcon name={title} icon={icon} size="sm" />
      <h1 className="max-w-[14rem] truncate text-[15px] font-semibold">{title}</h1>
      <nav className="ml-2 inline-flex gap-0.5 rounded-lg bg-slate-100 p-0.5">
        {tabs.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              cn(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors",
                isActive
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-800",
              )
            }
          >
            <t.Icon className="h-3.5 w-3.5" />
            {t.label}
          </NavLink>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-2">{right}</div>
    </div>
  );
}
