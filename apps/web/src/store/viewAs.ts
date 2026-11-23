// 서비스 관리자의 '권한 미리보기' 상태. 이 탭에서만 유지한다(탭을 닫으면 끝).
// 켜 두면 요청마다 X-Genio-View-As 헤더가 붙고, 서버도 그 역할로 판단한다(내 권한보다 낮은 역할만).
import { create } from "zustand";
import type { Role } from "@/lib/api/types";

const KEY = "genio.viewas";

export interface ViewAsTarget {
  /** 미리 보는 역할 */
  role: Role;
  /** 끝내면 돌아갈 내 진짜 역할 */
  back: Role | null;
}

function load(): ViewAsTarget | null {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as ViewAsTarget) : null;
  } catch {
    return null;
  }
}

function save(t: ViewAsTarget | null): void {
  try {
    if (t) window.sessionStorage.setItem(KEY, JSON.stringify(t));
    else window.sessionStorage.removeItem(KEY);
  } catch {
    // 저장소를 못 써도 현재 화면에서는 동작한다.
  }
}

interface ViewAsState {
  target: ViewAsTarget | null;
  enter: (t: ViewAsTarget) => void;
  exit: () => ViewAsTarget | null;
}

export const useViewAs = create<ViewAsState>((set, get) => ({
  target: load(),
  enter: (t) => {
    save(t);
    set({ target: t });
  },
  exit: () => {
    const prev = get().target;
    save(null);
    set({ target: null });
    return prev;
  },
}));

/** 지금 권한 미리보기 중이면 요청에 붙일 헤더 */
export function viewAsHeaders(): Record<string, string> {
  const t = useViewAs.getState().target;
  return t ? { "X-Genio-View-As": t.role } : {};
}
