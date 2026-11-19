// 데이터 표 칸 값: 칸 종류에 맞게 화면 글 ↔ 저장 값으로 바꾼다.
import type { DataColumn, DataColumnType } from "@/lib/api/types";

export const COLUMN_TYPES: { value: DataColumnType; label: string }[] = [
  { value: "text", label: "글" },
  { value: "number", label: "숫자" },
  { value: "boolean", label: "예/아니오" },
  { value: "date", label: "날짜" },
  { value: "json", label: "묶음 값(JSON)" },
];

export const KEY_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

/** 저장 값 → 입력칸 글 */
export function toText(v: unknown, type: DataColumnType): string {
  if (v === null || v === undefined) return "";
  if (type === "json") return typeof v === "string" ? v : JSON.stringify(v, null, 2);
  if (type === "boolean") return v ? "true" : "false";
  if (type === "date" && typeof v === "string") return v.slice(0, 10);
  return typeof v === "string" ? v : JSON.stringify(v);
}

export type Parsed = { ok: true; value: unknown } | { ok: false; error: string };

/** 입력칸 글 → 저장 값(빈 칸은 null) */
export function fromText(text: string, type: DataColumnType): Parsed {
  const t = text.trim();
  if (t === "") return { ok: true, value: null };
  switch (type) {
    case "number": {
      const n = Number(t.replace(/,/g, ""));
      return Number.isFinite(n) ? { ok: true, value: n } : { ok: false, error: "숫자가 아니에요" };
    }
    case "boolean":
      return { ok: true, value: t === "true" };
    case "date":
      return /^\d{4}-\d{2}-\d{2}/.test(t)
        ? { ok: true, value: t }
        : { ok: false, error: "날짜는 2026-11-03처럼 적어요" };
    case "json":
      try {
        return { ok: true, value: JSON.parse(t) as unknown };
      } catch {
        return { ok: false, error: "JSON 형식이 맞지 않아요" };
      }
    default:
      return { ok: true, value: text };
  }
}

/** 표에 보여 줄 짧은 글 */
export function display(v: unknown, type: DataColumnType): string {
  if (v === null || v === undefined || v === "") return "";
  if (type === "boolean") return v ? "예" : "아니오";
  if (type === "number" && typeof v === "number") return v.toLocaleString();
  if (type === "date" && typeof v === "string") {
    const d = new Date(v);
    return Number.isNaN(d.getTime()) ? v : d.toLocaleDateString("ko-KR");
  }
  return typeof v === "string" ? v : JSON.stringify(v);
}

/** 칸 정의 검사: 키 형식·중복·이름. 문제가 없으면 null. */
export function columnsProblem(cols: DataColumn[]): string | null {
  const seen = new Set<string>();
  for (const c of cols) {
    if (!c.key.trim()) return "칸 키가 비어 있어요.";
    if (!KEY_RE.test(c.key))
      return `칸 키 '${c.key}'는 영문·숫자·_만 쓰고 숫자로 시작할 수 없어요.`;
    if (seen.has(c.key)) return `칸 키 '${c.key}'가 두 번 있어요.`;
    seen.add(c.key);
  }
  return null;
}

/** 칸 이름에서 키를 만든다(영문이 없으면 col1, col2…) */
export function suggestKey(label: string, index: number, taken: string[]): string {
  let base = label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!base || !KEY_RE.test(base)) base = `col${index + 1}`;
  let key = base;
  let n = 2;
  while (taken.includes(key)) key = `${base}_${n++}`;
  return key;
}

/** 엑셀·구글 시트에서 복사한 표(탭 또는 쉼표로 나뉨) → 칸 정의 + 값(첫 줄은 칸 이름) */
export interface PastedTable {
  columns: DataColumn[];
  /** 칸 키 순서대로 정리한 값(숫자의 쉼표·날짜 모양 정리됨) */
  rows: string[][];
}

const DATE_RE = /^(\d{4})[-./](\d{1,2})[-./](\d{1,2})$/;

function normalizeDate(v: string): string | null {
  const m = DATE_RE.exec(v.trim());
  if (!m) return null;
  const [, y, mo, d] = m;
  return `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

export function parsePastedTable(raw: string): PastedTable | null {
  const lines = raw
    .replace(/\r/g, "")
    .split("\n")
    .filter((l) => l.trim() !== "");
  if (lines.length < 1) return null;
  const sep = lines[0]?.includes("\t") ? "\t" : lines[0]?.includes(",") ? "," : "\t";
  const cells = lines.map((l) => l.split(sep).map((c) => c.trim().replace(/^"(.*)"$/, "$1")));
  const header = cells[0] ?? [];
  if (header.length === 0 || header.every((h) => h === "")) return null;
  const body = cells.slice(1);
  const taken: string[] = [];
  const columns: DataColumn[] = header.map((h, i) => {
    const label = h || `칸 ${i + 1}`;
    const key = suggestKey(h, i, taken);
    taken.push(key);
    const values = body.map((r) => (r[i] ?? "").trim()).filter((v) => v !== "");
    let type: DataColumnType = "text";
    if (values.length > 0) {
      if (values.every((v) => /^-?\d[\d,]*(\.\d+)?$/.test(v) && !/^0\d/.test(v))) type = "number";
      else if (values.every((v) => normalizeDate(v) !== null)) type = "date";
    }
    return { key, label, type };
  });
  const rows = body.map((r) =>
    columns.map((c, i) => {
      const v = (r[i] ?? "").trim();
      if (c.type === "number") return v.replace(/,/g, "");
      if (c.type === "date") return normalizeDate(v) ?? v;
      return v;
    }),
  );
  return { columns, rows };
}

/** 칸 키 줄 + 값 줄로 CSV 글을 만든다(서버 가져오기가 첫 줄을 칸 키로 읽는다) */
export function toCsv(columns: DataColumn[], rows: string[][]): string {
  const q = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  return [columns.map((c) => q(c.key)).join(","), ...rows.map((r) => r.map(q).join(","))].join(
    "\n",
  );
}
