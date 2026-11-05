// 외부 추적 화면의 순수 계산: 서버 설정 ↔ 편집 중인 값, 필수 칸 확인, 전송 상태 문장
import type { TraceKind, TraceLast, TraceProvider, TraceProviderIn } from "@/lib/api/trace";

export const MAX_PROVIDERS = 10;
export const MAX_HEADERS = 8;

export interface HeaderDraft {
  name: string;
  /** 새로 넣은 값(비우면 저장된 값을 그대로 둔다) */
  value: string;
  /** 저장된 값의 ****abcd */
  masked: string;
}

export interface ProviderDraft {
  /** 화면에서만 쓰는 열쇠(저장 전에도 구분하려고) */
  uid: string;
  /** 서버가 정한 id. 아직 저장 안 한 서비스는 빈 글 */
  id: string;
  kind: string;
  name: string;
  enabled: boolean;
  sample_rate: number;
  only_failed: boolean;
  fields: Record<string, string>;
  /** 새로 넣은 비밀 값 */
  secrets: Record<string, string>;
  clear_secrets: string[];
  headers: HeaderDraft[];
}

let counter = 0;
export function nextUid(): string {
  counter += 1;
  return `draft-${counter}`;
}

export function kindOf(kinds: TraceKind[], kind: string): TraceKind | undefined {
  return kinds.find((k) => k.kind === kind);
}

/** 서버 설정 한 개를 편집용 값으로 */
export function toDraft(p: TraceProvider): ProviderDraft {
  return {
    uid: p.id,
    id: p.id,
    kind: p.kind,
    name: p.name,
    enabled: p.enabled,
    sample_rate: p.sample_rate,
    only_failed: p.only_failed,
    fields: { ...p.fields },
    secrets: {},
    clear_secrets: [],
    headers: p.headers.map((h) => ({ name: h.name, value: "", masked: h.masked })),
  };
}

/** 추가 메뉴에서 고른 서비스의 빈 설정(기본값을 미리 채운다) */
export function newDraft(kind: TraceKind): ProviderDraft {
  const fields: Record<string, string> = {};
  for (const f of kind.fields) {
    if (f.type === "text" || f.type === "url") fields[f.key] = f.default;
  }
  return {
    uid: nextUid(),
    id: "",
    kind: kind.kind,
    name: kind.label,
    enabled: false,
    sample_rate: 100,
    only_failed: false,
    fields,
    secrets: {},
    clear_secrets: [],
    headers: [],
  };
}

export function clampRate(n: number): number {
  if (!Number.isFinite(n)) return 100;
  return Math.max(0, Math.min(100, Math.round(n)));
}

/** 저장할 때 서버에 보내는 모양 */
export function toPayload(d: ProviderDraft): TraceProviderIn {
  return {
    ...(d.id ? { id: d.id } : {}),
    kind: d.kind,
    name: d.name.trim() || d.kind,
    enabled: d.enabled,
    sample_rate: clampRate(d.sample_rate),
    only_failed: d.only_failed,
    fields: d.fields,
    secrets: Object.fromEntries(Object.entries(d.secrets).filter(([, v]) => v.trim() !== "")),
    clear_secrets: d.clear_secrets,
    headers: d.headers
      .filter((h) => h.name.trim() !== "")
      .map((h) => ({ name: h.name.trim(), value: h.value })),
  };
}

/** 필수 칸이 모두 찼나(서버 저장값 + 새로 넣은 값 기준). 비어 있는 칸 이름 목록을 돌려준다. */
export function missingFields(
  d: ProviderDraft,
  kind: TraceKind | undefined,
  saved: TraceProvider | undefined,
): string[] {
  if (!kind) return [];
  const out: string[] = [];
  for (const f of kind.fields) {
    if (!f.required) continue;
    if (f.type === "secret") {
      const typed = (d.secrets[f.key] ?? "").trim() !== "";
      const stored = Boolean(saved?.secrets[f.key]?.has) && !d.clear_secrets.includes(f.key);
      if (!typed && !stored) out.push(f.label);
    } else if (f.type !== "headers") {
      const v = (d.fields[f.key] ?? "").trim() || f.default;
      if (!v) out.push(f.label);
    }
  }
  return out;
}

/** 편집한 값이 저장된 값과 다른가(시험은 저장된 키로 하므로 안내에 쓴다) */
export function isDirty(d: ProviderDraft, saved: TraceProvider | undefined): boolean {
  if (!saved) return true;
  if (
    d.name !== saved.name ||
    d.enabled !== saved.enabled ||
    clampRate(d.sample_rate) !== saved.sample_rate ||
    d.only_failed !== saved.only_failed
  )
    return true;
  if (Object.values(d.secrets).some((v) => v.trim() !== "") || d.clear_secrets.length > 0)
    return true;
  if (d.headers.length !== saved.headers.length) return true;
  if (d.headers.some((h, i) => h.value.trim() !== "" || h.name !== saved.headers[i]?.name))
    return true;
  return Object.keys(d.fields).some((k) => (d.fields[k] ?? "") !== (saved.fields[k] ?? ""));
}

/** 마지막 전송 결과 한 줄 문장 */
export function lastText(last: TraceLast | null | undefined, format: (iso: string) => string) {
  if (!last) return { tone: "gray" as const, text: "아직 보낸 기록이 없어요" };
  const when = format(last.at);
  return last.ok
    ? { tone: "green" as const, text: `${when} 보냄 · ${last.message}` }
    : { tone: "red" as const, text: `${when} 실패 · ${last.message}` };
}
