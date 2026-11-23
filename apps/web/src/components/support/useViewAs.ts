import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import type { Role } from "@/lib/api/types";
import { useSession } from "@/store/session";
import { useViewAs } from "@/store/viewAs";

/** 권한 미리보기를 켜거나(역할) 끈다(null). 캐시를 비우고 홈으로 가서 그 역할의 화면으로 새로 시작한다. */
export function useChangeViewAs() {
  const workspaceId = useSession((s) => s.workspaceId);
  const role = useSession((s) => s.role);
  const setWorkspace = useSession((s) => s.setWorkspace);
  const qc = useQueryClient();
  const navigate = useNavigate();
  return (next: Role | null) => {
    if (next === null) {
      const prev = useViewAs.getState().exit();
      if (prev) setWorkspace(workspaceId, prev.back);
    } else {
      const back = useViewAs.getState().target?.back ?? role;
      useViewAs.getState().enter({ role: next, back });
      setWorkspace(workspaceId, next);
    }
    qc.clear();
    navigate("/");
  };
}
