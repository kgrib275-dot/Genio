// 실행 결과 속 '목록(표)'을 찾아 표로 보여 주고 엑셀(CSV)로 내려받게 돕는 함수들
const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

export interface TableData {
  columns: string[];
  rows: Record<string, unknown>[];
}

/** 값 안에서 '같은 모양의 항목이 여러 개 있는 목록'을 찾는다(맨 위 또는 한두 단계 안쪽). */
export function findTable(value: unknown, depth = 0): TableData | null {
  if (Array.isArray(value)) {
    const rows = value.filter(isObj);
    if (rows.length >= 2 && rows.length === value.length) {
      const columns: string[] = [];
      for (const r of rows.slice(0, 200))
        for (const k of Object.keys(r)) if (!columns.includes(k)) columns.push(k);
      if (columns.length > 0 && columns.length <= 30) return { columns, rows };
    }
    return null;
  }
  if (isObj(value) && depth < 2) {
    for (const v of Object.values(value)) {
      const t = findTable(v, depth + 1);
      if (t) return t;
    }
  }
  return null;
}

function cell(v: unknown): string {
  if (v === null || v === undefined) return "";
  let s = typeof v === "object" ? JSON.stringify(v) : String(v);
  // 엑셀이 수식으로 읽지 않게(=, +, -, @로 시작하면 앞에 ' 를 붙인다)
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** 엑셀에서 한글이 깨지지 않게 BOM을 붙인 CSV 글 */
export function toCsv(t: TableData): string {
  const head = t.columns.map(cell).join(",");
  const body = t.rows.map((r) => t.columns.map((c) => cell(r[c])).join(","));
  return "\ufeff" + [head, ...body].join("\r\n");
}
