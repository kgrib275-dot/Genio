// v0.6 도움·문의 창 열기, 화면 투어 다시 보기, 사용설명서 찾기(어느 화면에서나 부른다)
import { HELP_SECTIONS, type HelpSection } from "@/help/content";
import { norm } from "@/lib/useListControls";

/** 도움·문의 창을 연다(HelpWidget이 듣고 있다). 창이 없으면 false. */
export function openHelp(tab: "help" | "feedback" = "help", message = ""): boolean {
  const ev = new CustomEvent("genio:open-help", { detail: { tab, message }, cancelable: true });
  window.dispatchEvent(ev);
  return ev.defaultPrevented;
}

/** 전체 검색창(Ctrl+K)을 연다(Layout이 듣고 있다). */
export function openPalette(): void {
  window.dispatchEvent(new CustomEvent("genio:open-palette"));
}

/** 단축키 보기 창을 연다(Layout이 듣고 있다). */
export function openShortcuts(): void {
  window.dispatchEvent(new CustomEvent("genio:open-shortcuts"));
}

/** 첫 로그인 화면 투어를 다시 보여 준다(Layout이 듣고 있다). */
export function startTour(): void {
  window.dispatchEvent(new CustomEvent("genio:start-tour"));
}

function textOf(s: HelpSection): string {
  const body = s.blocks.map((b) => ("text" in b ? b.text : b.items.join(" "))).join(" ");
  return `${s.title} ${s.summary} ${body}`.replace(/\*\*|`/g, "");
}

/** 검색어에 맞는 사용설명서 단락(낱말이 모두 들어간 것) */
export function searchHelp(query: string, sections: HelpSection[] = HELP_SECTIONS): HelpSection[] {
  const words = norm(query).split(" ").filter(Boolean);
  if (!words.length) return sections;
  return sections.filter((s) => {
    const t = norm(textOf(s));
    return words.every((w) => t.includes(w));
  });
}
