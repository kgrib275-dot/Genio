// 받은 값(JSON)에서 '값 연결'에 쓸 위치 목록을 만든다. 예: issue.title, answers[0].text
export interface PathItem {
  path: string;
  /** 화면에 보여 줄 짧은 예시 값 */
  sample: string;
}

const MAX_DEPTH = 6;
const MAX_ARRAY = 5;

function show(v: unknown): string {
  const text = typeof v === "string" ? v : JSON.stringify(v);
  const oneLine = text.replace(/\s+/g, " ").trim();
  return oneLine.length > 60 ? `${oneLine.slice(0, 59)}…` : oneLine;
}

/** 값(글·숫자·참거짓)이 있는 끝 위치만 모은다. 목록은 앞 5개만, 너무 깊거나 많으면 잘라 낸다. */
export function flattenPaths(value: unknown, limit = 80): PathItem[] {
  const out: PathItem[] = [];
  const walk = (v: unknown, path: string, depth: number) => {
    if (out.length >= limit || depth > MAX_DEPTH) return;
    if (v === null || v === undefined) return;
    if (Array.isArray(v)) {
      v.slice(0, MAX_ARRAY).forEach((x, i) => walk(x, `${path}[${i}]`, depth + 1));
      return;
    }
    if (typeof v === "object") {
      for (const [k, x] of Object.entries(v as Record<string, unknown>)) {
        walk(x, path ? `${path}.${k}` : k, depth + 1);
      }
      return;
    }
    if (path) out.push({ path, sample: show(v) });
  };
  walk(value, "", 0);
  return out;
}

/** 위치·예시 값에 검색어가 들어 있는 것만(대소문자 무시). */
export function filterPaths(items: PathItem[], query: string): PathItem[] {
  const q = query.trim().toLowerCase();
  if (!q) return items;
  return items.filter((i) => `${i.path} ${i.sample}`.toLowerCase().includes(q));
}
