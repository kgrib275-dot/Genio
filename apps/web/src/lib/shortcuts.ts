// 단축키 목록(단축키 보기 창·캔버스 도움말이 함께 쓴다). 실제로 동작하는 것만 적는다.

export const IS_MAC =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
export const MOD = IS_MAC ? "⌘" : "Ctrl";

export type ShortcutRow = [keys: string, what: string];

export const GLOBAL_SHORTCUTS: ShortcutRow[] = [
  [`${MOD} + K`, "전체 검색창 열기(앱·지식베이스·화면 찾기)"],
  ["Shift + ?", "단축키 보기"],
  ["Esc", "열린 창 닫기"],
];

export const PALETTE_SHORTCUTS: ShortcutRow[] = [
  ["↑  ↓", "결과 고르기"],
  ["Enter", "고른 곳으로 가기"],
  ["Esc", "닫기"],
];

export const CANVAS_SHORTCUTS: ShortcutRow[] = [
  [`${MOD} + C / V`, "복사 / 붙여넣기"],
  [`${MOD} + D`, "복제"],
  ["D", "단계 끄기·켜기"],
  ["Delete", "지우기"],
  [`${MOD} + Z`, "되돌리기"],
  [`${MOD} + Shift + Z, ${MOD} + Y`, "다시 하기"],
  ["Shift + 끌기", "여러 개 고르기"],
  [`${MOD} + 누르기`, "하나씩 더 고르기"],
  ["오른쪽 클릭", "단계 메뉴"],
];

export const CHAT_SHORTCUTS: ShortcutRow[] = [
  ["Enter", "메시지 보내기(내 설정에서 바꿀 수 있어요)"],
  [`${MOD} + Enter`, "Enter를 줄바꿈으로 바꿨을 때 보내기"],
];

/** 글을 치는 중이면(입력칸·코드 편집기·글상자) 화면 단축키를 쓰지 않는다. */
export function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  return Boolean(el.closest?.(".monaco-editor"));
}

/** 키 입력이 검색창 열기(Ctrl/⌘ + K)인지 */
export function isPaletteKey(
  e: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey">,
): boolean {
  return (e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k";
}

/** 키 입력이 단축키 보기(Shift + ?)인지. 글 치는 중이면 따로 걸러야 한다. */
export function isHelpKey(
  e: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey">,
): boolean {
  return !e.ctrlKey && !e.metaKey && !e.altKey && e.key === "?";
}
