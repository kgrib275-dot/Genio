// v0.6 지식베이스 훅: 질문·답 표 가져오기, 문서 처리 순서 미리 보기, 전체 다시 나누기(docs/api.md)
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { KbDocumentV2, KbSettings, PipelinePreview, QaColumns } from "@/lib/api/types";

function fileForm(file: File, extra: Record<string, string | undefined> = {}): FormData {
  const form = new FormData();
  form.append("file", file);
  for (const [k, v] of Object.entries(extra)) if (v) form.append(k, v);
  return form;
}

export function useQaColumns(kbId: string) {
  return useMutation({
    mutationFn: (file: File) =>
      api.upload<QaColumns>(`/knowledge-bases/${kbId}/qa/columns`, fileForm(file)),
  });
}

export function useImportQa(kbId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { file: File; question_column?: string; answer_column?: string }) =>
      api.upload<KbDocumentV2>(
        `/knowledge-bases/${kbId}/documents/qa`,
        fileForm(v.file, { question_column: v.question_column, answer_column: v.answer_column }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["documents", kbId] });
      void qc.invalidateQueries({ queryKey: ["kbs"] });
    },
  });
}

export function usePreviewPipeline(kbId: string) {
  return useMutation({
    mutationFn: (v: { file?: File; documentId?: string; settings: Partial<KbSettings> }) => {
      const form = new FormData();
      if (v.file) form.append("file", v.file);
      if (v.documentId) form.append("document_id", v.documentId);
      form.append("settings", JSON.stringify(v.settings));
      return api.upload<PipelinePreview>(`/knowledge-bases/${kbId}/preview`, form);
    },
  });
}

export function useReprocessKb(kbId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<{ queued: number }>(`/knowledge-bases/${kbId}/reprocess`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["documents", kbId] }),
  });
}
