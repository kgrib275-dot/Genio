// v0.6 처음 쓰는 사람 안내: 시작 체크리스트 상태, 안내 진행 상태 저장, 의견·문의
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { Me, OnboardingPref } from "@/lib/api/types";

export interface OnboardingStatus {
  ai_connected: boolean;
  samples_installed: boolean;
  app_created: boolean;
  test_run: boolean;
  version_saved: boolean;
  deployed: boolean;
  team_invited: boolean;
}

export function useOnboardingStatus(ws: string, enabled = true) {
  return useQuery({
    queryKey: ["onboarding", ws],
    queryFn: () => api.get<OnboardingStatus>(`/workspaces/${ws}/onboarding`),
    enabled: Boolean(ws) && enabled,
    staleTime: 15_000,
  });
}

/** 안내 진행 상태(투어 끝남·체크리스트 닫음 등)를 내 계정에 저장한다. */
export function useSaveOnboarding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: OnboardingPref) => api.patch<Me>("/me", { preferences: { onboarding: v } }),
    onMutate: (v) => {
      const me = qc.getQueryData<Me>(["me"]);
      if (me)
        qc.setQueryData<Me>(["me"], {
          ...me,
          preferences: {
            ...me.preferences,
            onboarding: { ...(me.preferences?.onboarding ?? {}), ...v },
          },
        });
    },
    onSuccess: (me) => qc.setQueryData(["me"], me),
  });
}

export type FeedbackKind = "question" | "bug" | "idea" | "other";

export interface FeedbackItem {
  id: string;
  user_email: string | null;
  user_name: string | null;
  kind: FeedbackKind;
  message: string;
  page: string;
  created_at: string;
}

export function useSendFeedback(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { kind: FeedbackKind; message: string; page: string }) =>
      api.post<{ ok: boolean }>(`/workspaces/${ws}/feedback`, v),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["feedback", ws] }),
  });
}

export function useFeedbackList(ws: string, enabled = true) {
  return useQuery({
    queryKey: ["feedback", ws],
    queryFn: () => api.get<FeedbackItem[]>(`/workspaces/${ws}/feedback`),
    enabled: Boolean(ws) && enabled,
  });
}
