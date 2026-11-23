// 서비스 관리자의 '지원 접속' 상태. 이 탭에서만 유지한다(탭을 닫으면 끝). 요청마다 X-Genio-Support 헤더가 붙는다.
import { create } from "zustand";
import type { Role } from "@/lib/api/types";

const KEY = "genio.support";

export interface SupportTarget {
  id: string;
  name: string;
  /** 회사가 허용한 수준: read(보기만) · edit(수정까지) */
  level: "read" | "edit";
  /** 지원을 끝내면 돌아갈 내 워크스페이스 */
  back: { id: string; role: Role | null };
}

function load(): SupportTarget | null {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as SupportTarget) : null;
  } catch {
    return null;
  }
}

function save(t: SupportTarget | null): void {
  try {
    if (t) window.sessionStorage.setItem(KEY, JSON.stringify(t));
    else window.sessionStorage.removeItem(KEY);
  } catch {
    // 저장소를 못 써도 현재 화면에서는 동작한다.
  }
}

interface SupportState {
  target: SupportTarget | null;
  enter: (t: SupportTarget) => void;
  exit: () => SupportTarget | null;
}

export const useSupport = create<SupportState>((set, get) => ({
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

/** 지금 지원 접속 중이면 요청에 붙일 헤더 */
export function supportHeaders(): Record<string, string> {
  return useSupport.getState().target ? { "X-Genio-Support": "1" } : {};
}
