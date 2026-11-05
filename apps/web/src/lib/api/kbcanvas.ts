// v0.9 지식 처리 캔버스·이미지 색인: 단계별 미리 보기, 처리 순서 모음, 그림 설명 비용 어림(docs/api.md)
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { ChunkMode, KbDocumentV2, KbSettings } from "@/lib/api/types";

export type StageType =
  "extract" | "clean" | "split" | "translate" | "summarize" | "metadata" | "image" | "store";

export interface Stage {
  type: StageType;
  enabled: boolean;
  collapse_spaces?: boolean;
  mask_urls?: boolean;
  mask_emails?: boolean;
  remove_repeated_lines?: boolean;
  remove_patterns?: string[];
  fixed?: Record<string, string>;
  filename_pattern?: string;
  target_language?: string;
  max_images?: number;
  min_size?: number;
}

/** 서버가 단계마다 돌려주는 결과(없는 값은 빠질 수 있다) */
export interface StageResult {
  enabled?: boolean;
  skipped?: string | null;
  chars?: number;
  sample?: string;
  before_chars?: number;
  after_chars?: number;
  before_sample?: string;
  after_sample?: string;
  chunks?: number;
  mode?: string;
  samples?: Array<string | { before?: string; after?: string; summary?: string }>;
  language?: string;
  calls?: number;
  calls_full?: number;
  estimated_cost_usd?: number | null;
  cut?: number;
  tags?: Record<string, string>;
  found?: number;
  images?: number;
  described?: number;
  failed?: number;
  truncated?: number;
  too_small?: number;
  duplicates?: number;
  model?: string;
  errors?: string[];
}

export interface CanvasChunk {
  index: number;
  content: string;
  parent_content: string | null;
  question?: string;
  answer?: string;
  char_count: number;
  kind?: "text" | "image";
  image?: { caption: string | null; page: number | null; index: number | null };
  thumb?: string;
}

export interface CanvasPreview {
  total: number;
  chunks: CanvasChunk[];
  metadata: Record<string, string>;
  log: string[];
  text_preview: string;
  chunk_mode: ChunkMode;
  stages: Partial<Record<StageType, StageResult>>;
  ai_calls: number;
}

export interface PipelineTemplate {
  id: string;
  name: string;
  description: string;
  settings: Partial<KbSettings> & { pipeline: Stage[] };
}

export interface ImageEstimate {
  documents: number;
  scanned: number;
  partial: boolean;
  images: number;
  vision_calls: number;
  estimated_cost_usd: number | null;
  model: string | null;
  model_ok: boolean;
  message: string;
  enabled: boolean;
  budget_message: string;
}

/** 문서별 그림 보고(없으면 null) */
export interface ImageReport {
  found?: number;
  images?: number;
  described?: number;
  failed?: number;
  calls?: number;
  truncated?: number;
  skipped?: string | null;
}

export type KbDocWithImages = KbDocumentV2 & { image_report?: ImageReport | null };

/** 검색 결과·인용에 붙는 그림 참조. url은 공개 챗에서만 서버가 붙인 24시간 서명 주소 */
export interface CitationImage {
  file_id: string;
  caption?: string | null;
  page?: number | null;
  kb_id?: string | null;
  url?: string;
}

export function usePreviewCanvas(kbId: string) {
  return useMutation({
    mutationFn: (v: { file?: File; documentId?: string; settings: Record<string, unknown> }) => {
      const form = new FormData();
      if (v.file) form.append("file", v.file);
      if (v.documentId) form.append("document_id", v.documentId);
      form.append("settings", JSON.stringify(v.settings));
      return api.upload<CanvasPreview>(`/knowledge-bases/${kbId}/preview`, form);
    },
  });
}

export function usePipelineTemplates() {
  return useQuery({
    queryKey: ["kb-pipeline-templates"],
    queryFn: () => api.get<PipelineTemplate[]>("/knowledge-pipeline-templates"),
    staleTime: 10 * 60_000,
  });
}

export function useImageEstimate(
  kbId: string,
  opts: { maxImages: number; minSize: number },
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["kb-image-estimate", kbId, opts.maxImages, opts.minSize],
    queryFn: () =>
      api.get<ImageEstimate>(
        `/knowledge-bases/${kbId}/image-estimate?max_images=${opts.maxImages}&min_size=${opts.minSize}`,
      ),
    enabled,
    staleTime: 30_000,
  });
}
