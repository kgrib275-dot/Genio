import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useLoggedIn } from "@/app/useAuthState";
import { useMe } from "@/lib/api/auth";
import { ForcePasswordChange } from "@/pages/auth/ForcePasswordChange";

export function RequireAuth({ children }: { children: ReactNode }) {
  const loggedIn = useLoggedIn();
  const location = useLocation();
  const me = useMe(loggedIn);
  if (!loggedIn) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  // 관리자가 내준 임시 비밀번호는 새 비밀번호를 정한 뒤에야 쓸 수 있다
  if (me.data?.must_change_password) return <ForcePasswordChange name={me.data.name} />;
  return <>{children}</>;
}
