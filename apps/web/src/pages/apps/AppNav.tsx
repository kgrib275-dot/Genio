import {
  Activity,
  CalendarClock,
  ChevronLeft,
  KeyRound,
  MessagesSquare,
  Rocket,
  SlidersHorizontal,
  Wand2,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { AppIcon } from "@/components/AppIcon";
import type { HelpPageKey } from "@/help/content";
import { HelpButton } from "@/help/HelpButton";
import { cn } from "@/lib/cn";
import { canEdit, canViewRuns, useSession } from "@/store/session";

interface Tab {
  to: string;
  label: string;
  Icon: LucideIcon;
  /** 이 탭이 함께 켜져 보일 다른 주소(예: 실행 기록은 로그 탭) */
  also?: string[];
}

export function AppNav({
  appId,
  title,
  icon,
  right,
  help,
}: {
  appId: string;
  title: string;
  icon?: string;
  right?: ReactNode;
  help?: HelpPageKey;
}) {
  const role = useSession((s) => s.role);
  const { pathname } = useLocation();
  const base = `/apps/${appId}`;
  const tabs: Tab[] = [
    ...(canEdit(role)
      ? [
          { to: `${base}/builder`, label: "만들기", Icon: Wand2 },
          { to: `${base}/features`, label: "기능", Icon: SlidersHorizontal },
        ]
      : []),
    ...(canViewRuns(role)
      ? [{ to: `${base}/triggers`, label: "자동 실행", Icon: CalendarClock }]
      : []),
    ...(canViewRuns(role)
      ? [
          { to: `${base}/logs`, label: "로그", Icon: MessagesSquare, also: [`${base}/runs`] },
          { to: `${base}/monitor`, label: "모니터링", Icon: Activity },
        ]
      : []),
    ...(canEdit(role) ? [{ to: `${base}/api`, label: "API", Icon: KeyRound }] : []),
    { to: `${base}/settings`, label: "배포·설정", Icon: Rocket },
  ];
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-slate-200 bg-white px-3 py-2 sm:px-4 lg:h-14 lg:flex-nowrap lg:py-0">
      <div className="flex min-w-0 items-center gap-2">
        <Link
          to="/"
          title="내 앱으로"
          aria-label="내 앱으로"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-900"
        >
          <ChevronLeft className="h-5 w-5" />
        </Link>
        <AppIcon name={title} icon={icon} size="sm" />
        <h1 className="max-w-[10rem] truncate text-[15px] font-semibold sm:max-w-[14rem]">
          {title}
        </h1>
        {help && <HelpButton page={help} />}
      </div>
      <nav
        aria-label="앱 메뉴"
        className="-mx-1 order-3 flex w-full gap-0.5 overflow-x-auto px-1 pb-0.5 lg:order-none lg:mx-0 lg:w-auto lg:rounded-lg lg:bg-slate-100 lg:p-0.5"
      >
        {tabs.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              cn(
                "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors",
                isActive || t.also?.some((a) => pathname.startsWith(a))
                  ? "bg-indigo-50 text-indigo-700 lg:bg-white lg:text-slate-900 lg:shadow-sm"
                  : "text-slate-500 hover:text-slate-800",
              )
            }
          >
            <t.Icon className="h-3.5 w-3.5" />
            {t.label}
          </NavLink>
        ))}
      </nav>
      {right && (
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2">{right}</div>
      )}
    </div>
  );
}
