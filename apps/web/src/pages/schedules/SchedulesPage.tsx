import { CalendarClock } from "lucide-react";
import { Link } from "react-router-dom";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { HelpButton } from "@/help/HelpButton";
import { Badge } from "@/components/ui/badge";
import { useSchedules } from "@/lib/api/schedules";
import { formatDate } from "@/lib/cn";
import { describeCron } from "@/lib/cron";
import { useSession } from "@/store/session";

const STATUS: Record<string, string> = { succeeded: "성공", failed: "실패", running: "실행 중" };

/** 예약 실행 달력: 앞으로 7일 동안 언제 무엇이 도는지와 전체 예약 목록 */
export default function SchedulesPage() {
  const ws = useSession((s) => s.workspaceId);
  const q = useSchedules(ws);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const d = q.data;
  if (!d) return null;
  const days = new Map<string, typeof d.upcoming>();
  for (const u of d.upcoming) {
    const key = new Date(u.at).toLocaleDateString("ko-KR", {
      month: "long",
      day: "numeric",
      weekday: "short",
    });
    days.set(key, [...(days.get(key) ?? []), u]);
  }
  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
      <div>
        <h1 className="flex items-center gap-1 text-xl font-bold text-slate-900">
          예약 실행 <HelpButton page="schedules" />
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          정해 둔 시간에 저절로 도는 흐름이에요. 앞으로 7일 일정과 지난 결과를 한눈에 봐요.
        </p>
      </div>
      {d.items.length === 0 ? (
        <EmptyState
          icon={<CalendarClock className="h-8 w-8 text-slate-300" />}
          title="아직 예약한 흐름이 없어요"
          description="앱의 '자동 실행' 탭에서 '매일 오전 9시'처럼 예약을 만들 수 있어요."
        />
      ) : (
        <>
          <section
            aria-label="앞으로 7일"
            className="rounded-2xl border border-slate-200 bg-white p-4"
          >
            <h2 className="mb-2 text-sm font-semibold text-slate-800">앞으로 7일</h2>
            {days.size === 0 && (
              <p className="text-sm text-slate-500">7일 안에 예정된 실행이 없어요.</p>
            )}
            {[...days.entries()].map(([day, list]) => (
              <div key={day} className="border-t border-slate-100 py-2 first:border-t-0">
                <p className="text-xs font-semibold text-slate-500">{day}</p>
                <ul className="mt-1 space-y-0.5">
                  {list.map((u, i) => (
                    <li key={`${u.trigger_id}-${i}`} className="flex gap-3 text-sm">
                      <span className="w-14 tabular-nums text-slate-500">
                        {new Date(u.at).toLocaleTimeString("ko-KR", {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                      <span className="text-slate-800">
                        {u.app_name}
                        {u.name && <span className="text-slate-400"> · {u.name}</span>}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </section>
          <section aria-label="예약 목록" className="rounded-2xl border border-slate-200 bg-white">
            <h2 className="px-4 pt-4 text-sm font-semibold text-slate-800">예약 목록</h2>
            <ul className="mt-2 divide-y divide-slate-100">
              {d.items.map((s) => (
                <li
                  key={s.id}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-sm"
                >
                  <Link
                    to={`/apps/${s.app_id}/triggers`}
                    className="font-medium text-indigo-700 hover:underline"
                  >
                    {s.app_name}
                  </Link>
                  <span className="text-slate-600">{describeCron(s.cron)}</span>
                  {!s.enabled && <Badge tone="gray">꺼짐</Badge>}
                  <span className="ml-auto text-xs text-slate-500">
                    다음 {formatDate(s.next_run_at)} · 지난번 {formatDate(s.last_run_at)}
                    {s.last_status ? ` (${STATUS[s.last_status] ?? s.last_status})` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
