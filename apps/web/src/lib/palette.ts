// 전체 검색창(Ctrl+K)의 순수 함수: 검색어 강조, 결과 펼치기, 키보드 이동, 최근 항목 기억.
import type { PaletteGroup, PaletteItem } from "@/lib/api/search";

export interface Segment {
  text: string;
  hit: boolean;
}

/** 글에서 검색어와 같은 부분(대소문자 무시)을 찾아 조각으로 나눈다. */
export function highlight(text: string, query: string): Segment[] {
  const q = query.trim();
  if (!q) return [{ text, hit: false }];
  const lower = text.toLowerCase();
  const ql = q.toLowerCase();
  const out: Segment[] = [];
  let at = 0;
  for (;;) {
    const i = lower.indexOf(ql, at);
    if (i < 0) break;
    if (i > at) out.push({ text: text.slice(at, i), hit: false });
    out.push({ text: text.slice(i, i + q.length), hit: true });
    at = i + q.length;
  }
  if (at < text.length) out.push({ text: text.slice(at), hit: false });
  return out.length ? out : [{ text, hit: false }];
}

export interface Row extends PaletteItem {
  kind: string;
  label: string;
}

/** 그룹들을 위에서 아래 순서의 한 줄 목록으로 펼친다(키보드 이동용). */
export function flatten(groups: PaletteGroup[]): Row[] {
  return groups.flatMap((g) => g.items.map((i) => ({ ...i, kind: g.kind, label: g.label })));
}

/** ↑↓로 한 칸씩 옮긴다(끝에서 반대쪽으로 돈다). 목록이 비면 0. */
export function moveIndex(current: number, delta: number, count: number): number {
  if (count <= 0) return 0;
  return (((current + delta) % count) + count) % count;
}

// ---------------- 최근 열어 본 것 ----------------
const RECENT_KEY = "genio.palette.recent";
const RECENT_MAX = 6;

function key(ws: string): string {
  return `${RECENT_KEY}.${ws}`;
}

export function readRecents(ws: string): Row[] {
  try {
    const raw = window.localStorage.getItem(key(ws));
    const list = raw ? (JSON.parse(raw) as unknown) : [];
    if (!Array.isArray(list)) return [];
    return list.filter(
      (r): r is Row =>
        !!r && typeof r.id === "string" && typeof r.title === "string" && typeof r.to === "string",
    );
  } catch {
    return [];
  }
}

/** 방금 연 항목을 맨 앞에 기억한다(같은 곳은 한 번만, 최대 6개). */
export function pushRecent(ws: string, row: Row): Row[] {
  const next = [row, ...readRecents(ws).filter((r) => !(r.kind === row.kind && r.id === row.id))];
  const cut = next.slice(0, RECENT_MAX);
  try {
    window.localStorage.setItem(key(ws), JSON.stringify(cut));
  } catch {
    // 기억하지 못해도 동작에는 문제없다
  }
  return cut;
}
