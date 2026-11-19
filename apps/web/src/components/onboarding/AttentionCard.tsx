import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ClipboardList, ThumbsDown } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api/client";
import { useOpenTaskCount } from "@/lib/api/v5a";
import { useSession } from "@/store/session";

interface Attention {
  failed: { app_id: string; app_name: string; count: number }[];
  disliked: { app_id: string; app_name: string; count: number }[];
}

/** 홈 맨 위: 지금 해야 할 일(승인 대기, 실패한 실행, 싫어요 받은 답)만 모아서 보여 준다. 없으면 안 보인다. */
export function AttentionCard() {
  const ws = useSession((s) => s.workspaceId);
  const tasks = useOpenTaskCount(ws);
  const q = useQuery({
    queryKey: ["attention", ws],
    queryFn: () => api.get<Attention>(`/workspaces/${ws}/attention`),
    enabled: Boolean(ws),
    refetchInterval: 60_000,
  });
  const open = tasks.data?.open ?? 0;
  const failed = q.data?.failed ?? [];
  const disliked = q.data?.disliked ?? [];
  if (open === 0 && failed.length === 0 && disliked.length === 0) return null;
  const row = "flex items-center gap-2 rounded-lg px-3 py-2 text-sm hover:bg-slate-50";
  return (
    <section
      aria-label="지금 할 일"
      className="mb-6 rounded-2xl border border-amber-200 bg-amber-50/50 p-4"
    >
      <p className="mb-2 text-sm font-semibold text-slate-800">지금 할 일</p>
      <div className="space-y-0.5">
        {open > 0 && (
          <Link to="/tasks" className={row}>
            <ClipboardList className="h-4 w-4 text-indigo-500" />
            승인·확인을 기다리는 일이 <b>{open}건</b> 있어요
          </Link>
        )}
        {failed.map((f) => (
          <Link key={`f${f.app_id}`} to={`/apps/${f.app_id}/logs`} className={row}>
            <AlertTriangle className="h-4 w-4 text-red-500" />
            <span>
              &apos;{f.app_name}&apos;이(가) 오늘 <b>{f.count}번 실패</b>했어요 — 이유 보기
            </span>
          </Link>
        ))}
        {disliked.map((d) => (
          <Link key={`d${d.app_id}`} to={`/apps/${d.app_id}/logs`} className={row}>
            <ThumbsDown className="h-4 w-4 text-amber-600" />
            <span>
              &apos;{d.app_name}&apos;의 답 <b>{d.count}개</b>가 싫어요를 받았어요 — 고치러 가기
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}
