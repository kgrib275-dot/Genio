// 예약 실행 달력(워크스페이스 전체)
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface ScheduleItem {
  id: string;
  app_id: string;
  app_name: string;
  name: string;
  enabled: boolean;
  cron: string;
  timezone: string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string | null;
}

export interface ScheduleOverview {
  items: ScheduleItem[];
  upcoming: { at: string; trigger_id: string; app_name: string; name: string }[];
}

export function useSchedules(ws: string) {
  return useQuery({
    queryKey: ["schedules", ws],
    queryFn: () => api.get<ScheduleOverview>(`/workspaces/${ws}/schedules`),
    enabled: Boolean(ws),
    refetchInterval: 60_000,
  });
}
