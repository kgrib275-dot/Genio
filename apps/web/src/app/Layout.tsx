import { useEffect } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Select } from "@/components/ui/input";
import { ko } from "@/i18n/ko";
import { useMe } from "@/lib/api/auth";
import { signOut } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { useSession } from "@/store/session";

const NAV = [
  { to: "/", label: ko.nav.dashboard, icon: "🏠", end: true },
  { to: "/knowledge", label: ko.nav.knowledge, icon: "📚" },
  { to: "/connectors", label: ko.nav.connectors, icon: "🔌" },
  { to: "/market", label: ko.nav.market, icon: "🛍️" },
  { to: "/workspace", label: ko.nav.workspace, icon: "👥" },
];

export function Layout() {
  const me = useMe();
  const { workspaceId, setWorkspace } = useSession();
  const navigate = useNavigate();

  // 선택한 워크스페이스가 목록에 없으면 첫 번째로 맞춘다.
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
      <aside className="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="px-4 py-4">
          <p className="text-lg font-bold text-indigo-700">{ko.appName}</p>
          <p className="text-xs text-slate-500">{ko.tagline}</p>
        </div>
        <div className="px-3 pb-3">
          <Select
            aria-label="워크스페이스"
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
          </Select>
          {current && (
            <p className="mt-1 px-1 text-xs text-slate-500">내 역할: {ko.roles[current.role]}</p>
          )}
        </div>
        <nav className="flex-1 space-y-0.5 px-2">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-sm",
                  isActive
                    ? "bg-indigo-50 font-medium text-indigo-700"
                    : "text-slate-700 hover:bg-slate-100",
                )
              }
            >
              <span aria-hidden>{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-100 px-4 py-3 text-sm">
          <p className="truncate font-medium">{me.data?.name}</p>
          <p className="truncate text-xs text-slate-500">{me.data?.email}</p>
          <button
            type="button"
            className="mt-2 text-xs text-slate-500 hover:text-slate-900"
            onClick={() => {
              signOut();
              navigate("/login");
            }}
          >
            {ko.common.logout}
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
