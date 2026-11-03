// v0.6 문서 처리 순서: 단계 이름·설명과 화면용 기본값(서버 kb_pipeline.py와 같은 순서)
import type { PipelineStep, PipelineStepType } from "@/lib/api/types";

export const STEP_INFO: Record<PipelineStepType, { label: string; desc: string; always: boolean }> =
  {
    extract: {
      label: "1. 글 꺼내기",
      desc: "PDF·DOCX·PPTX·XLSX·HTML·TXT에서 글자를 꺼내요.",
      always: true,
    },
    clean: {
      label: "2. 글 정리",
      desc: "빈칸 줄이기, 쪽마다 되풀이되는 머리글·바닥글 지우기, 주소·이메일 가리기.",
      always: false,
    },
    split: {
      label: "3. 조각 나누기",
      desc: "설정의 나누기 방식(일반·부모-자식·질문·답)대로 나눠요.",
      always: true,
    },
    metadata: {
      label: "4. 꼬리표 붙이기",
      desc: "모든 문서에 같은 꼬리표를 붙이거나 파일 이름에서 꼬리표를 뽑아요.",
      always: false,
    },
    store: { label: "5. 저장", desc: "조각을 검색할 수 있게 저장해요(임베딩).", always: true },
  };

export const STEP_ORDER: PipelineStepType[] = ["extract", "clean", "split", "metadata", "store"];

const DEFAULTS: Record<PipelineStepType, PipelineStep> = {
  extract: { type: "extract", enabled: true },
  clean: {
    type: "clean",
    enabled: false,
    collapse_spaces: true,
    mask_urls: false,
    mask_emails: false,
    remove_repeated_lines: false,
    remove_patterns: [],
  },
  split: { type: "split", enabled: true },
  metadata: { type: "metadata", enabled: false, fixed: {}, filename_pattern: "" },
  store: { type: "store", enabled: true },
};

/** 저장된 설정을 정해진 순서·기본값으로 맞춘다(빠진 단계는 채움). */
export function normalizePipeline(raw: PipelineStep[] | null | undefined): PipelineStep[] {
  const given = new Map((raw ?? []).map((s) => [s.type, s]));
  return STEP_ORDER.map((t) => {
    const merged = { ...DEFAULTS[t], ...(given.get(t) ?? {}), type: t };
    if (STEP_INFO[t].always) merged.enabled = true;
    return merged;
  });
}

/** "부서=인사, 연도=2026" ↔ {부서: "인사", 연도: "2026"} */
export function parsePairs(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of text.split(/[,\n]/)) {
    const i = part.indexOf("=");
    if (i <= 0) continue;
    const k = part.slice(0, i).trim();
    if (k) out[k] = part.slice(i + 1).trim();
  }
  return out;
}

export function formatPairs(pairs: Record<string, string> | undefined): string {
  return Object.entries(pairs ?? {})
    .map(([k, v]) => `${k}=${v}`)
    .join(", ");
}
