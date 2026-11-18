// 후속(O2): 효과 리포트 — 앱마다 아낀 시간(추정)
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface ImpactRow {
  app_id: string;
  app_name: string;
  succeeded_runs: number;
  minutes_per_run: number;
  saved_minutes: number;
}

export interface ImpactReport {
  apps: ImpactRow[];
  total_succeeded_runs: number;
  total_saved_minutes: number;
  total_saved_hours: number;
  /** 성공은 했지만 '한 번에 아끼는 시간'을 정하지 않은 앱 수 */
  unset_apps: number;
  estimate: boolean;
}

export function useImpact(ws: string, range: { from?: string; to?: string } = {}) {
  return useQuery({
    queryKey: ["impact", ws, range],
    queryFn: () => {
      const sp = new URLSearchParams();
      if (range.from) sp.set("from", range.from);
      if (range.to) sp.set("to", range.to);
      const q = sp.toString();
      return api.get<ImpactReport>(`/workspaces/${ws}/impact${q ? `?${q}` : ""}`);
    },
    enabled: Boolean(ws),
  });
}

/** 분을 '2시간 30분'처럼 */
export function formatMinutes(min: number): string {
  if (min <= 0) return "0분";
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (h === 0) return `${m}분`;
  return m === 0 ? `${h}시간` : `${h}시간 ${m}분`;
}
