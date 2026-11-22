import { AnnouncementBanner } from "@/components/announcement/AnnouncementBanner";
import { usePublicStatus } from "@/lib/api/announcement";
import { cn } from "@/lib/cn";

const LABEL = { ok: "정상", degraded: "일부 느림", down: "장애" } as const;
const DOT = { ok: "bg-emerald-500", degraded: "bg-amber-500", down: "bg-red-500" } as const;
const HEAD = {
  ok: "모든 서비스가 정상이에요",
  degraded: "일부 기능이 느리거나 불안정해요",
  down: "지금 서비스에 문제가 있어요",
} as const;

/** 로그인 없이 볼 수 있는 서비스 상태 페이지 */
export default function StatusPage() {
  const q = usePublicStatus();
  const d = q.data;
  return (
    <div className="min-h-[100dvh] bg-slate-50">
      <AnnouncementBanner />
      <main className="mx-auto max-w-xl px-4 py-12">
        <h1 className="text-2xl font-bold text-slate-900">제니오 서비스 상태</h1>
        {q.isLoading && <p className="mt-6 text-slate-500">확인하는 중이에요…</p>}
        {q.isError && (
          <p role="alert" className="mt-6 rounded-lg bg-red-50 px-4 py-3 text-red-800">
            상태를 불러오지 못했어요. 서비스에 접속할 수 없는 상태일 수 있어요. 잠시 뒤에 다시
            확인해 주세요.
          </p>
        )}
        {d && (
          <>
            <p
              className={cn(
                "mt-6 rounded-xl px-4 py-3 text-base font-semibold",
                d.status === "ok" && "bg-emerald-50 text-emerald-800",
                d.status === "degraded" && "bg-amber-50 text-amber-900",
                d.status === "down" && "bg-red-50 text-red-800",
              )}
            >
              {HEAD[d.status]}
            </p>
            <ul className="mt-4 divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
              {d.components.map((c) => (
                <li key={c.name} className="flex items-center gap-3 px-4 py-3 text-sm">
                  <span className={cn("h-2.5 w-2.5 rounded-full", DOT[c.status])} />
                  <span className="flex-1 text-slate-800">{c.name}</span>
                  <span className="text-slate-500">{LABEL[c.status]}</span>
                </li>
              ))}
            </ul>
            <p className="mt-4 text-xs text-slate-400">30초마다 새로 확인해요.</p>
          </>
        )}
      </main>
    </div>
  );
}
