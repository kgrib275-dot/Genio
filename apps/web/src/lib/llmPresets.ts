// AI 공급자 목록(v0.6) 화면 도우미: 묶음별 정리, 이름 찾기, 저장할 값 만들기
import type { ProviderPreset } from "@/lib/api/types";

/** 서버 목록을 받기 전·실패했을 때 쓰는 기본 5종 */
export const FALLBACK_PRESETS: ProviderPreset[] = [
  preset("anthropic", "Anthropic (Claude)", "claude-sonnet-5-5"),
  preset("openai", "OpenAI (GPT)", "gpt-4o-mini"),
  preset("google", "Google (Gemini)", "gemini-2.0-flash"),
  { ...preset("azure", "Azure OpenAI", ""), needs_base_url: true },
  { ...preset("openai-compatible", "OpenAI 호환 (직접 입력)", ""), needs_base_url: true },
];

function preset(key: string, name: string, model: string): ProviderPreset {
  return {
    key,
    name,
    group: key === "openai-compatible" ? "직접 입력" : "기본",
    base_url: null,
    default_model: model,
    models: model ? [{ model, label: model, vision: true, json: true }] : [],
    note: "",
    native: true,
    needs_base_url: false,
    embedding: false,
    vision: Boolean(model),
  };
}

/** 묶음 순서를 지키며 묶는다(서버가 정한 순서 그대로) */
export function groupPresets(list: ProviderPreset[]): { group: string; items: ProviderPreset[] }[] {
  const out: { group: string; items: ProviderPreset[] }[] = [];
  for (const p of list) {
    const last = out.find((g) => g.group === p.group);
    if (last) last.items.push(p);
    else out.push({ group: p.group, items: [p] });
  }
  return out;
}

/** 저장된 연결의 공급자 키 → 화면 이름 */
export function presetName(list: ProviderPreset[], key: string): string {
  return list.find((p) => p.key === key)?.name ?? key;
}

/** 주소 칸: 꼭 받아야 하면 입력값 그대로, preset이면 비워 두어 기본 주소를 쓰게 한다 */
export function baseUrlToSend(p: ProviderPreset | undefined, typed: string): string | undefined {
  const v = typed.trim();
  if (!v) return undefined;
  if (p && !p.needs_base_url && p.base_url && v === p.base_url) return undefined;
  return v;
}
