// 서비스 공지와 공개 상태
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface Announcement {
  active: boolean;
  message: string;
  level: "info" | "warn" | "maintenance";
  until: string | null;
}

export function useAnnouncement() {
  return useQuery({
    queryKey: ["announcement"],
    queryFn: () => api.get<Announcement>("/announcement"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

export function useSaveAnnouncement() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { message: string; level: Announcement["level"]; until: string | null }) =>
      api.put<Announcement>("/admin/announcement", v),
    onSuccess: (data) => qc.setQueryData(["announcement"], data),
  });
}

export interface PublicStatus {
  status: "ok" | "degraded" | "down";
  components: { name: string; status: "ok" | "degraded" | "down" }[];
  announcement: Announcement;
}

export function usePublicStatus() {
  return useQuery({
    queryKey: ["public-status"],
    queryFn: () => api.get<PublicStatus>("/public-status"),
    refetchInterval: 30_000,
  });
}
