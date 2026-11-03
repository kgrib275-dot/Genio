import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
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
    ...(canEdit(role) ? [{ to: `/apps/${appId}/builder`, label: "만들기" }] : []),
    { to: `/apps/${appId}/runs`, label: "실행 기록" },
    { to: `/apps/${appId}/settings`, label: "배포·설정" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2">
      <span className="text-xl" aria-hidden>
        {icon || "🤖"}
      </span>
      <h1 className="max-w-[16rem] truncate text-base font-semibold">{title}</h1>
      <nav className="flex gap-1">
        {tabs.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              cn(
                "rounded px-2.5 py-1 text-sm",
                isActive
                  ? "bg-indigo-50 font-medium text-indigo-700"
                  : "text-slate-600 hover:bg-slate-100",
              )
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-2">{right}</div>
    </div>
  );
}
