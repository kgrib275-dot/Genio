// 단계 결과(여러 겹의 값)를 '경로 = 값' 목록으로 펼친다. 값 확인창이 쓴다.
// 경로는 `{{단계.경로}}`에 그대로 넣을 수 있는 형식이다(예: body.rates.KRW, items[0].name).

export interface FlatValue {
  path: string;
  text: string;
  kind: "string" | "number" | "boolean" | "empty" | "list" | "object";
}

const MAX_DEPTH = 4;
const MAX_ITEMS = 5;
const MAX_ROWS = 200;

function leaf(path: string, v: unknown): FlatValue {
  if (v === null || v === undefined) return { path, text: "(비어 있음)", kind: "empty" };
  if (typeof v === "string") return { path, text: v, kind: "string" };
  if (typeof v === "number") return { path, text: String(v), kind: "number" };
  if (typeof v === "boolean") return { path, text: v ? "예" : "아니요", kind: "boolean" };
  return { path, text: JSON.stringify(v), kind: "object" };
}

function walk(path: string, v: unknown, depth: number, out: FlatValue[]): void {
  if (out.length >= MAX_ROWS) return;
  if (Array.isArray(v)) {
    out.push({ path, text: `목록 ${v.length}개`, kind: "list" });
    if (depth >= MAX_DEPTH) return;
    v.slice(0, MAX_ITEMS).forEach((item, i) => walk(`${path}[${i}]`, item, depth + 1, out));
    if (v.length > MAX_ITEMS) {
      out.push({
        path: `${path}[…]`,
        text: `나머지 ${v.length - MAX_ITEMS}개는 생략`,
        kind: "empty",
      });
    }
    return;
  }
  if (v !== null && typeof v === "object") {
    const entries = Object.entries(v as Record<string, unknown>).filter(
      ([k]) => !k.startsWith("__"),
    );
    if (depth >= MAX_DEPTH) {
      out.push({ path, text: JSON.stringify(v), kind: "object" });
      return;
    }
    if (entries.length === 0) {
      out.push({ path, text: "(빈 값)", kind: "empty" });
      return;
    }
    for (const [k, child] of entries) walk(path ? `${path}.${k}` : k, child, depth + 1, out);
    return;
  }
  out.push(leaf(path, v));
}

/** 결과 한 개를 경로별 값 목록으로 만든다. "__"로 시작하는 내부 값은 뺀다. */
export function flattenValue(value: unknown): FlatValue[] {
  const out: FlatValue[] = [];
  if (value === null || value === undefined) return out;
  if (typeof value === "object" && !Array.isArray(value)) {
    for (const [k, child] of Object.entries(value as Record<string, unknown>)) {
      if (k.startsWith("__")) continue;
      walk(k, child, 1, out);
    }
    return out;
  }
  walk("값", value, 1, out);
  return out;
}

/** `{{단계.경로}}` 형식으로 만든다(값 끌어오기 칸에 붙여 넣을 수 있다). */
export function refPath(nodeId: string, path: string): string {
  return `{{${nodeId}.${path}}}`;
}

/** 검색어가 경로나 값에 들어 있는지(대소문자·공백 무시) */
export function matchesQuery(item: FlatValue, q: string): boolean {
  const n = q.trim().toLowerCase();
  if (!n) return true;
  return `${item.path} ${item.text}`.toLowerCase().includes(n);
}
