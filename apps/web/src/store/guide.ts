// 진행 중인 가이드(어느 가이드의 몇 번째 단계인지). 이 브라우저에 기억해 두고 화면을 옮겨도 이어진다.
import { create } from "zustand";
import { guideById } from "@/lib/guides";

const KEY = "genio.guide";

export interface ActiveGuide {
  id: string;
  step: number;
}

function load(): ActiveGuide | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const v = JSON.parse(raw) as ActiveGuide;
    const guide = guideById(v.id);
    if (!guide || !Number.isInteger(v.step) || v.step < 0 || v.step >= guide.steps.length) {
      return null;
    }
    return v;
  } catch {
    return null;
  }
}

function save(v: ActiveGuide | null): void {
  try {
    if (v) window.localStorage.setItem(KEY, JSON.stringify(v));
    else window.localStorage.removeItem(KEY);
  } catch {
    // 저장하지 못해도 이번 화면에서는 동작한다.
  }
}

interface GuideState {
  active: ActiveGuide | null;
  /** 가이드를 처음부터 시작한다 */
  start: (id: string) => void;
  /** 단계를 옮긴다(범위를 벗어나면 무시) */
  go: (step: number) => void;
  /** 그만두거나 끝낸다 */
  stop: () => void;
}

export const useGuide = create<GuideState>((set, get) => ({
  active: load(),
  start: (id) => {
    if (!guideById(id)) return;
    const next = { id, step: 0 };
    save(next);
    set({ active: next });
  },
  go: (step) => {
    const cur = get().active;
    const guide = cur ? guideById(cur.id) : undefined;
    if (!cur || !guide || step < 0 || step >= guide.steps.length) return;
    const next = { id: cur.id, step };
    save(next);
    set({ active: next });
  },
  stop: () => {
    save(null);
    set({ active: null });
  },
}));
