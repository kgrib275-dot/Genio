// v0.9 문서 처리 순서(8단계): 단계 이름·설명과 화면용 기본값(서버 kb_pipeline.py와 같은 순서)
import type { Stage, StageType } from "@/lib/api/kbcanvas";
import type { KbSettings } from "@/lib/api/types";

export interface StageInfo {
  /** 캔버스 칸에 쓰는 짧은 이름 */
  label: string;
  desc: string;
  /** 항상 도는 단계(끌 수 없음) */
  always: boolean;
  /** AI를 불러서 비용이 드는 단계(기본 꺼짐) */
  ai: boolean;
}

export const STEP_INFO: Record<StageType, StageInfo> = {
  extract: {
    label: "글 꺼내기",
    desc: "PDF·DOCX·PPTX·XLSX·HTML·TXT에서 글자를 꺼내요.",
    always: true,
    ai: false,
  },
  clean: {
    label: "글 정리",
    desc: "빈칸 줄이기, 쪽마다 되풀이되는 머리글·바닥글 지우기, 주소·이메일 가리기.",
    always: false,
    ai: false,
  },
  split: {
    label: "조각 나누기",
    desc: "설정의 나누기 방식(일반·부모-자식·질문·답)대로 나눠요.",
    always: true,
    ai: false,
  },
  translate: {
    label: "번역",
    desc: "조각을 다른 언어로 바꿔 저장해요. 조각마다 AI를 불러서 비용이 들어요.",
    always: false,
    ai: true,
  },
  summarize: {
    label: "요약 붙이기",
    desc: "조각마다 한 줄 요약을 만들어 검색에 쓰는 글 앞에 붙여요. 조각마다 AI를 불러서 비용이 들어요.",
    always: false,
    ai: true,
  },
  metadata: {
    label: "꼬리표",
    desc: "모든 문서에 같은 꼬리표를 붙이거나 파일 이름에서 꼬리표를 뽑아요.",
    always: false,
    ai: false,
  },
  image: {
    label: "이미지 설명",
    desc: "문서 속 그림을 AI가 글로 설명해 검색되게 해요. 그림 한 장마다 AI를 불러서 비용이 들어요.",
    always: false,
    ai: true,
  },
  store: {
    label: "저장",
    desc: "조각을 검색할 수 있게 저장해요(임베딩).",
    always: true,
    ai: false,
  },
};

export const STEP_ORDER: StageType[] = [
  "extract",
  "clean",
  "split",
  "translate",
  "summarize",
  "metadata",
  "image",
  "store",
];

const DEFAULTS: Record<StageType, Stage> = {
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
  translate: { type: "translate", enabled: false, target_language: "영어" },
  summarize: { type: "summarize", enabled: false },
  metadata: { type: "metadata", enabled: false, fixed: {}, filename_pattern: "" },
  image: { type: "image", enabled: false, max_images: 20, min_size: 100 },
  store: { type: "store", enabled: true },
};

/** 저장된 설정을 정해진 순서·기본값으로 맞춘다(빠진 단계는 채움, 예전 5단계 형식도 읽는다). */
export function normalizePipeline(
  raw: ReadonlyArray<{ type: string }> | null | undefined,
): Stage[] {
  const given = new Map<string, Record<string, unknown>>();
  for (const s of raw ?? []) given.set(s.type, s as unknown as Record<string, unknown>);
  return STEP_ORDER.map((t) => {
    const merged = { ...DEFAULTS[t], ...(given.get(t) ?? {}), type: t } as Stage;
    if (STEP_INFO[t].always) merged.enabled = true;
    return merged;
  });
}

/** 켜져 있는 AI 단계(비용이 드는 단계) */
export function enabledAiStages(steps: Stage[]): StageType[] {
  return steps.filter((s) => s.enabled && STEP_INFO[s.type].ai).map((s) => s.type);
}

export interface TemplateLike {
  settings: Partial<KbSettings> & { pipeline: Stage[] };
}

/** 모음을 고르면 처리 순서와 나누기 설정이 통째로 바뀐다(저장은 사용자가 따로 누른다). */
export function templateToDraft(tpl: TemplateLike): {
  steps: Stage[];
  overrides: Partial<KbSettings>;
} {
  const { pipeline, ...rest } = tpl.settings;
  return { steps: normalizePipeline(pipeline), overrides: rest };
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
