import {
  ClipboardList,
  GraduationCap,
  Gauge,
  BookMarked,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Table2,
  LayoutGrid,
  Lock,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  Plus,
  Settings,
  Shield,
  Store,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Avatar } from "@/components/AppIcon";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ProjectDialog, ProjectDot } from "@/components/projects/ProjectDialog";
import { ko } from "@/i18n/ko";
import { useMe } from "@/lib/api/auth";
import { signOut } from "@/lib/api/client";
import { useOpenTaskCount } from "@/lib/api/v5a";
import type { Me, Role } from "@/lib/api/types";
import { useProjects } from "@/lib/api/v3";
import { cn } from "@/lib/cn";
import { rememberEnterToSend } from "@/lib/composer";
import { canManage, canViewRuns, useSession } from "@/store/session";
import { applyFontSize, applyTheme } from "@/store/theme";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  show?: (role: Role | null) => boolean;
}

const NAV: NavItem[] = [
  { to: "/", label: ko.nav.dashboard, icon: LayoutGrid, end: true },
  { to: "/tasks", label: "작업함", icon: ClipboardList },
  { to: "/knowledge", label: ko.nav.knowledge, icon: BookOpen },
  { to: "/data", label: "데이터 표", icon: Table2 },
  { to: "/connectors", label: ko.nav.connectors, icon: Plug },
  { to: "/market", label: ko.nav.market, icon: Store },
  { to: "/workspace", label: ko.nav.workspace, icon: Users },
  { to: "/admin", label: "관리", icon: Shield, show: canManage },
];

const BOTTOM_NAV: NavItem[] = [
  { to: "/learn", label: "배우기", icon: GraduationCap },
  { to: "/help", label: "사용설명서", icon: BookMarked },
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

function NavItems({
  items,
  compact,
  role,
  onNavigate,
  badges = {},
}: {
  items: NavItem[];
  compact: boolean;
  role: Role | null;
  onNavigate?: () => void;
  /** 메뉴 옆 숫자(예: 작업함의 열린 일 수) */
  badges?: Record<string, number>;
}) {
  return (
    <>
      {items
        .filter((n) => !n.show || n.show(role))
        .map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            title={compact ? n.label : undefined}
            onClick={onNavigate}
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
            <span className="relative inline-flex shrink-0">
              <n.icon className="h-[18px] w-[18px] shrink-0" strokeWidth={2} />
              {compact && (badges[n.to] ?? 0) > 0 && (
                <span className="absolute -right-1.5 -top-1.5 h-2 w-2 rounded-full bg-red-500" />
              )}
            </span>
            {!compact && <span className="min-w-0 flex-1 truncate">{n.label}</span>}
            {!compact && (badges[n.to] ?? 0) > 0 && (
              <span
                className="ml-auto rounded-full bg-red-500 px-1.5 text-[11px] font-semibold leading-5 text-white"
                aria-label={`처리할 일 ${badges[n.to]}개`}
              >
                {(badges[n.to] ?? 0) > 99 ? "99+" : badges[n.to]}
              </span>
            )}
          </NavLink>
        ))}
    </>
  );
}

function SidebarBody({
  me,
  compact,
  inApp,
  onTogglePin,
  onNavigate,
}: {
  me: Me | undefined;
  compact: boolean;
  inApp: boolean;
  onTogglePin?: () => void;
  onNavigate?: () => void;
}) {
  const { workspaceId, role, setWorkspace } = useSession();
  const openTasks = useOpenTaskCount(workspaceId);
  const navigate = useNavigate();
  const workspaces = me?.workspaces ?? [];
  const current = workspaces.find((w) => w.id === workspaceId);
  return (
    <>
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

      <nav className={cn("flex-1 space-y-0.5 overflow-y-auto", compact ? "px-2" : "px-3")}>
        <NavItems
          items={NAV}
          compact={compact}
          role={role}
          onNavigate={onNavigate}
          badges={{ "/tasks": openTasks.data?.open ?? 0 }}
        />
        {!compact && <ProjectsSection myUserId={me?.id} onNavigate={onNavigate} />}
      </nav>

      <div className={cn("space-y-0.5 pb-2", compact ? "px-2" : "px-3")}>
        <NavItems items={BOTTOM_NAV} compact={compact} role={role} onNavigate={onNavigate} />
        {inApp && onTogglePin && (
          <button
            type="button"
            title={compact ? "메뉴 펼치기" : "메뉴 접기"}
            onClick={onTogglePin}
            className={cn(
              "flex w-full items-center gap-2 rounded-lg py-2 text-xs text-slate-500 hover:bg-slate-100",
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
      </div>

      <div
        className={cn(
          "flex items-center gap-2.5 border-t border-slate-100 py-3",
          compact ? "flex-col px-2" : "px-4",
        )}
      >
        <Link
          to="/settings"
          onClick={onNavigate}
          title="내 설정"
          className={cn(
            "flex min-w-0 items-center gap-2.5 rounded-lg hover:bg-slate-100",
            compact ? "p-0.5" : "-m-1 flex-1 p-1",
          )}
        >
          <Avatar name={me?.name ?? ""} />
          {!compact && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{me?.name}</p>
              <p className="truncate text-[11px] text-slate-500">
                {current ? ko.roles[current.role] : ""} · {me?.email}
              </p>
            </div>
          )}
        </Link>
        {!compact && (
          <Link
            to="/settings"
            onClick={onNavigate}
            title="내 설정"
            aria-label="내 설정"
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <Settings className="h-4 w-4" />
          </Link>
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
    </>
  );
}

const PROJECTS_OPEN_KEY = "genio.sidebar.projects";

function ProjectsSection({ myUserId, onNavigate }: { myUserId?: string; onNavigate?: () => void }) {
  const { workspaceId, role } = useSession();
  const projects = useProjects(workspaceId);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [params] = useSearchParams();
  const active = pathname === "/" ? params.get("project") : null;
  const [open, setOpen] = useState(() => {
    try {
      return window.localStorage.getItem(PROJECTS_OPEN_KEY) !== "0";
    } catch {
      return true;
    }
  });
  const [creating, setCreating] = useState(false);

  function toggle() {
    setOpen((v) => {
      try {
        window.localStorage.setItem(PROJECTS_OPEN_KEY, v ? "0" : "1");
      } catch {
        // 기억하지 못해도 동작에는 문제없다
      }
      return !v;
    });
  }

  const list = projects.data ?? [];
  return (
    <div className="pt-4">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="flex w-full items-center gap-1 rounded-md px-3 py-1 text-[11px] font-semibold text-slate-400 hover:text-slate-600"
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        프로젝트
        {list.length > 0 && <span className="ml-auto font-normal">{list.length}</span>}
      </button>
      {open && (
        <div className="mt-0.5 space-y-0.5">
          {canViewRuns(role) && (
            <Link
              to="/projects"
              onClick={onNavigate}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm transition-colors",
                pathname === "/projects"
                  ? "bg-indigo-50 font-semibold text-indigo-700"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
              )}
            >
              <Gauge className="h-[18px] w-[18px]" />
              <span className="min-w-0 flex-1 truncate">전체 현황</span>
            </Link>
          )}
          {list.map((p) => (
            <Link
              key={p.id}
              to={`/?project=${p.id}`}
              onClick={onNavigate}
              title={p.description || p.name}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm transition-colors",
                active === p.id
                  ? "bg-indigo-50 font-semibold text-indigo-700"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
              )}
            >
              <ProjectDot color={p.color} className="mx-1" />
              <span className="min-w-0 flex-1 truncate">{p.name}</span>
              {p.visibility === "private" && (
                <Lock className="h-3 w-3 shrink-0 text-slate-400" aria-label="비공개" />
              )}
            </Link>
          ))}
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100 hover:text-slate-900"
          >
            <Plus className="h-[18px] w-[18px]" /> 새 프로젝트
          </button>
        </div>
      )}
      <ProjectDialog
        ws={workspaceId}
        open={creating}
        onClose={() => setCreating(false)}
        myUserId={myUserId}
        onSaved={(p) => {
          onNavigate?.();
          navigate(`/?project=${p.id}`);
        }}
      />
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
  const [drawerOpen, setDrawerOpen] = useState(false);
  const compact = inApp && !pinnedOpen;

  useEffect(() => {
    const list = me.data?.workspaces ?? [];
    if (list.length === 0) return;
    const current = list.find((w) => w.id === workspaceId);
    if (current) {
      if (useSession.getState().role !== current.role) setWorkspace(current.id, current.role);
    } else {
      // 고른 워크스페이스가 없으면 '내 설정'의 기본 워크스페이스를 먼저 쓴다
      const pref = me.data?.preferences?.default_workspace_id;
      const pick = list.find((w) => w.id === pref) ?? list[0];
      if (pick) setWorkspace(pick.id, pick.role);
    }
  }, [me.data, workspaceId, setWorkspace]);

  // 서버에 저장된 테마·글자 크기를 이 기기에도 맞춘다
  const prefTheme = me.data?.preferences?.theme;
  const prefFont = me.data?.preferences?.font_size;
  useEffect(() => {
    if (prefTheme) applyTheme(prefTheme);
  }, [prefTheme]);
  useEffect(() => {
    if (prefFont) applyFontSize(prefFont);
  }, [prefFont]);
  const prefEnter = me.data?.preferences?.enter_to_send;
  useEffect(() => {
    if (typeof prefEnter === "boolean") rememberEnterToSend(prefEnter);
  }, [prefEnter]);

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

  // 화면을 옮기면 모바일 메뉴를 닫는다
  useEffect(() => setDrawerOpen(false), [pathname]);

  if (me.isLoading) return <Loading />;
  if (me.error)
    return (
      <div className="mx-auto max-w-md p-8">
        <ErrorBox error={me.error} />
      </div>
    );

  return (
    <div className="flex h-[100dvh] flex-col bg-slate-50 text-slate-900 md:flex-row">
      {/* 모바일 위쪽 막대 */}
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-3 md:hidden">
        <button
          type="button"
          aria-label="메뉴 열기"
          className="rounded-md p-1.5 text-slate-600 hover:bg-slate-100"
          onClick={() => setDrawerOpen(true)}
        >
          <Menu className="h-5 w-5" />
        </button>
        <Logo />
      </header>

      {drawerOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-slate-900/40"
            onClick={() => setDrawerOpen(false)}
            aria-hidden
          />
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-white shadow-xl">
            <div className="flex items-center justify-between px-4 py-4">
              <Logo />
              <button
                type="button"
                aria-label="메뉴 닫기"
                className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100"
                onClick={() => setDrawerOpen(false)}
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <SidebarBody
              me={me.data}
              compact={false}
              inApp={false}
              onNavigate={() => setDrawerOpen(false)}
            />
          </aside>
        </div>
      )}

      {/* 데스크톱 옆 메뉴 */}
      <aside
        className={cn(
          "hidden shrink-0 flex-col border-r border-slate-200 bg-white transition-[width] duration-200 md:flex",
          compact ? "w-[60px]" : "w-60",
        )}
      >
        <div className={cn("flex items-center py-4", compact ? "justify-center" : "px-4")}>
          <Logo compact={compact} />
        </div>
        <SidebarBody
          me={me.data}
          compact={compact}
          inApp={inApp}
          onTogglePin={() => setPinnedOpen((v) => !v)}
        />
      </aside>

      <main className="min-h-0 min-w-0 flex-1 overflow-y-auto">
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
  return <div className="mx-auto max-w-6xl px-4 py-6 sm:px-8 sm:py-8">{children}</div>;
}
