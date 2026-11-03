// 시험 호출용: 설정 값 안의 {{...}} 참조를 찾고, 시험용 값으로 바꾼다.
const REF = /\{\{\s*([^}]+?)\s*\}\}/g;

/** 값들(글·객체·배열) 안의 {{...}} 참조 이름을 중복 없이 모은다. */
export function refsIn(values: unknown[]): string[] {
  const out = new Set<string>();
  const walk = (v: unknown) => {
    if (typeof v === "string") for (const m of v.matchAll(REF)) out.add((m[1] ?? "").trim());
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === "object") Object.values(v).forEach(walk);
  };
  values.forEach(walk);
  return [...out].filter(Boolean);
}

/** {{참조}}를 시험용 값으로 바꾼다(없으면 빈 글). 객체·배열 안까지. */
export function fillRefs(v: unknown, samples: Record<string, string>): unknown {
  if (typeof v === "string")
    return v.replace(REF, (_m, name: string) => samples[String(name).trim()] ?? "");
  if (Array.isArray(v)) return v.map((x) => fillRefs(x, samples));
  if (v && typeof v === "object")
    return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, fillRefs(x, samples)]));
  return v;
}
