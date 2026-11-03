import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useLoggedIn } from "@/app/useAuthState";

export function RequireAuth({ children }: { children: ReactNode }) {
  const loggedIn = useLoggedIn();
  const location = useLocation();
  if (!loggedIn) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <>{children}</>;
}
