import {
  BookOpen,
  LayoutGrid,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  Store,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Avatar } from "@/components/AppIcon";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ko } from "@/i18n/ko";
import { useMe } from "@/lib/api/auth";
import { signOut } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { useSession } from "@/store/session";

const NAV: { to: string; label: string; icon: LucideIcon; end?: boolean }[] = [
  { to: "/", label: ko.nav.dashboard, icon: LayoutGrid, end: true },
  { to: "/knowledge", label: ko.nav.knowledge, icon: BookOpen },
  { to: "/connectors", label: ko.nav.connectors, icon: Plug },
  { to: "/market", label: ko.nav.market, icon: Store },
  { to: "/workspace", label: ko.nav.workspace, icon: Users },
];

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-sm font-bold text-white shadow-sm">
        G
      </span>
      {!compact && (
        <div className="leading-tight">
          <p className="text-[15px] font-bold text-slate-900">{ko.appName}</p>
          <p className="text-[11px] text-slate-500">{ko.tagline}</p>
        </div>
      )}
    </div>
  );
}

export function Layout() {
  const me = useMe();
  const { workspaceId, setWorkspace } = useSession();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  // 앱 화면(빌더 등)에서는 캔버스를 넓게 쓰도록 메뉴를 아이콘만 보이게 접는다.
  const inApp = pathname.startsWith("/apps/") || pathname.startsWith("/runs/");
  const [pinnedOpen, setPinnedOpen] = useState(false);
  const compact = inApp && !pinnedOpen;

  useEffect(() => {
    const list = me.data?.workspaces ?? [];
    if (list.length === 0) return;
    const current = list.find((w) => w.id === workspaceId);
    if (current) {
      if (useSession.getState().role !== current.role) setWorkspace(current.id, current.role);
    } else if (list[0]) {
      setWorkspace(list[0].id, list[0].role);
    }
  }, [me.data, workspaceId, setWorkspace]);

  // 대시보드가 뜬 뒤 한가할 때 무거운 화면(빌더 등) 코드를 미리 받아 두면, 눌렀을 때 바로 열린다.
  useEffect(() => {
    const warm = () => {
      void import("@/pages/apps/BuilderPage");
      void import("@/pages/apps/AppSettingsPage");
      void import("@/pages/market/MarketPage");
    };
    const w = window as Window & { requestIdleCallback?: (cb: () => void) => number };
    if (w.requestIdleCallback) w.requestIdleCallback(warm);
    else window.setTimeout(warm, 1500);
  }, []);

  useEffect(() => {
    const onLogout = () => navigate("/login");
    window.addEventListener("genio:logout", onLogout);
    return () => window.removeEventListener("genio:logout", onLogout);
  }, [navigate]);

  if (me.isLoading) return <Loading />;
  if (me.error)
    return (
      <div className="mx-auto max-w-md p-8">
        <ErrorBox error={me.error} />
      </div>
    );

  const workspaces = me.data?.workspaces ?? [];
  const current = workspaces.find((w) => w.id === workspaceId);

  return (
    <div className="flex h-screen bg-slate-50 text-slate-900">
      <aside
        className={cn(
          "flex shrink-0 flex-col border-r border-slate-200 bg-white transition-[width] duration-200",
          compact ? "w-[60px]" : "w-60",
        )}
      >
        <div className={cn("flex items-center py-4", compact ? "justify-center" : "px-4")}>
          <Logo compact={compact} />
        </div>

        {!compact && (
          <div className="px-3 pb-3">
            <label className="mb-1 block px-1 text-[11px] font-medium text-slate-400">
              워크스페이스
            </label>
            <select
              aria-label="워크스페이스"
              className="w-full truncate rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-sm font-medium text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
              value={workspaceId}
              onChange={(e) => {
                const w = workspaces.find((x) => x.id === e.target.value);
                if (w) setWorkspace(w.id, w.role);
              }}
            >
              {workspaces.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </div>
        )}

        <nav className={cn("flex-1 space-y-0.5", compact ? "px-2" : "px-3")}>
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              title={compact ? n.label : undefined}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 rounded-lg py-2 text-sm transition-colors",
                  compact ? "justify-center px-0" : "px-3",
                  isActive
                    ? "bg-indigo-50 font-semibold text-indigo-700"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                )
              }
            >
              <n.icon className="h-[18px] w-[18px] shrink-0" strokeWidth={2} />
              {!compact && n.label}
            </NavLink>
          ))}
        </nav>

        {inApp && (
          <button
            type="button"
            title={compact ? "메뉴 펼치기" : "메뉴 접기"}
            onClick={() => setPinnedOpen((v) => !v)}
            className={cn(
              "mx-2 mb-2 flex items-center gap-2 rounded-lg py-2 text-xs text-slate-500 hover:bg-slate-100",
              compact ? "justify-center" : "px-3",
            )}
          >
            {compact ? (
              <PanelLeftOpen className="h-4 w-4" />
            ) : (
              <>
                <PanelLeftClose className="h-4 w-4" /> 메뉴 접기
              </>
            )}
          </button>
        )}

        <div
          className={cn(
            "flex items-center gap-2.5 border-t border-slate-100 py-3",
            compact ? "flex-col px-2" : "px-4",
          )}
        >
          <Avatar name={me.data?.name ?? ""} />
          {!compact && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{me.data?.name}</p>
              <p className="truncate text-[11px] text-slate-500">
                {current ? ko.roles[current.role] : ""} · {me.data?.email}
              </p>
            </div>
          )}
          <button
            type="button"
            title={ko.common.logout}
            aria-label={ko.common.logout}
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            onClick={() => {
              signOut();
              navigate("/login");
            }}
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-y-auto">
        {workspaceId ? (
          <Outlet />
        ) : (
          <div className="p-8">
            <Loading label="워크스페이스를 고르는 중…" />
          </div>
        )}
      </main>
    </div>
  );
}

export function PageContainer({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-6xl px-8 py-8">{children}</div>;
}
