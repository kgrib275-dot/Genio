// 현재 선택한 워크스페이스. 새로고침해도 유지한다.
import { create } from "zustand";
import type { Role } from "@/lib/api/types";

const KEY = "genio.workspace";

function load(): string {
  try {
    return window.localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

interface SessionState {
  workspaceId: string;
  role: Role | null;
  setWorkspace: (id: string, role: Role | null) => void;
}

export const useSession = create<SessionState>((set) => ({
  workspaceId: load(),
  role: null,
  setWorkspace: (id, role) => {
    try {
      window.localStorage.setItem(KEY, id);
    } catch {
      // 저장소를 못 써도 현재 탭에서는 동작한다.
    }
    set({ workspaceId: id, role });
  },
}));

export const canEdit = (role: Role | null) =>
  role === "owner" || role === "admin" || role === "builder";
export const canManage = (role: Role | null) => role === "owner" || role === "admin";
export const canViewRuns = (role: Role | null) => canEdit(role) || role === "operator";
