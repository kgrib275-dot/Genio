// 개선이 필요한 질문: 답을 못 했거나 '싫어요'를 받은 질문을 모아 바로 고친다.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface ImprovementItem {
  message_id: string;
  question: string;
  answer: string;
  reason: "dislike" | "no_answer";
  comment: string;
  count: number;
  last_at: string;
}

export interface Improvements {
  open_count: number;
  items: ImprovementItem[];
}

export function useImprovements(appId: string, enabled = true) {
  return useQuery({
    queryKey: ["improvements", appId],
    queryFn: () => api.get<Improvements>(`/apps/${appId}/improvements`),
    enabled: Boolean(appId) && enabled,
  });
}

function useInvalidate(appId: string) {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["improvements", appId] });
    void qc.invalidateQueries({ queryKey: ["annotations", appId] });
  };
}

export function useAnswerImprovement(appId: string) {
  const done = useInvalidate(appId);
  return useMutation({
    mutationFn: (v: { messageId: string; answer: string }) =>
      api.post<{ annotation_id: string }>(`/apps/${appId}/improvements/${v.messageId}/answer`, {
        answer: v.answer,
      }),
    onSuccess: done,
  });
}

export function useDismissImprovement(appId: string) {
  const done = useInvalidate(appId);
  return useMutation({
    mutationFn: (messageId: string) =>
      api.post<{ dismissed: number }>(`/apps/${appId}/improvements/${messageId}/dismiss`),
    onSuccess: done,
  });
}
