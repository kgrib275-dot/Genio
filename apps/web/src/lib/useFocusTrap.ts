// 대화상자·검색창이 열려 있는 동안 Tab 키가 창 밖으로 나가지 않게 가두고, 닫으면 원래 자리로 돌려준다.
import { useEffect, type RefObject } from "react";

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]):not([type="hidden"]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

/** 창 안에서 Tab으로 갈 수 있는 요소들(숨김·비활성 제외) */
export function focusables(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => !el.hasAttribute("hidden") && el.getAttribute("aria-hidden") !== "true",
  );
}

/** Tab·Shift+Tab을 창 안에서 돌게 한다. 처리했으면 true. */
export function trapTab(e: KeyboardEvent, root: HTMLElement): boolean {
  if (e.key !== "Tab") return false;
  const items = focusables(root);
  if (items.length === 0) {
    e.preventDefault();
    root.focus();
    return true;
  }
  const first = items[0] as HTMLElement;
  const last = items[items.length - 1] as HTMLElement;
  const active = document.activeElement as HTMLElement | null;
  if (!active || !root.contains(active)) {
    e.preventDefault();
    first.focus();
    return true;
  }
  if (e.shiftKey && active === first) {
    e.preventDefault();
    last.focus();
    return true;
  }
  if (!e.shiftKey && active === last) {
    e.preventDefault();
    first.focus();
    return true;
  }
  return false;
}

/**
 * active가 true인 동안 root 안에 포커스를 가둔다. 열릴 때 포커스가 이미 안에 있으면(autoFocus)
 * 그대로 두고, 아니면 initial(없으면 첫 요소, 그것도 없으면 창 자체)로 옮긴다.
 * 닫히면 열기 전에 포커스가 있던 곳으로 돌려준다.
 */
export function useFocusTrap(
  ref: RefObject<HTMLElement | null>,
  active: boolean,
  initial?: RefObject<HTMLElement | null>,
): void {
  useEffect(() => {
    if (!active) return;
    const root = ref.current;
    if (!root) return;
    const before = document.activeElement as HTMLElement | null;
    if (!root.contains(document.activeElement)) {
      const scope = initial?.current ?? root;
      (focusables(scope)[0] ?? focusables(root)[0] ?? root).focus();
    }
    const onKey = (e: KeyboardEvent) => {
      trapTab(e, root);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (before && document.contains(before)) before.focus();
    };
  }, [active, ref, initial]);
}
