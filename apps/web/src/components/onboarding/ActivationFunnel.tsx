import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

interface Funnel {
  steps: { label: string; count: number; rate: number | null }[];
}

/** 멤버가 어디까지 해 봤는지(가입 → 앱 만들기 → 써 보기 → 공유). 어디서 막히는지 보려는 용도. */
export function ActivationFunnel({ ws }: { ws: string }) {
  const q = useQuery({
    queryKey: ["activation", ws],
    queryFn: () => api.get<Funnel>(`/workspaces/${ws}/activation`),
  });
  if (!q.data) return null;
  return (
    <section aria-label="첫 사용 현황" className="rounded-2xl border border-slate-200 bg-white p-4">
      <p className="text-sm font-semibold text-slate-800">첫 사용 현황</p>
      <p className="mb-3 text-xs text-slate-500">
        멤버가 어디까지 해 봤는지 보여 줘요. 비율이 갑자기 줄어드는 단계가 막히는 곳이에요.
      </p>
      <ul className="space-y-2">
        {q.data.steps.map((s) => (
          <li key={s.label} className="text-sm">
            <div className="flex justify-between">
              <span className="text-slate-700">{s.label}</span>
              <span className="text-slate-500">
                {s.count}
                {s.rate !== null ? ` (${Math.round(s.rate * 100)}%)` : ""}
              </span>
            </div>
            {s.rate !== null && (
              <div className="mt-1 h-1.5 rounded bg-slate-100">
                <div
                  className="h-1.5 rounded bg-indigo-500"
                  style={{ width: `${Math.round(s.rate * 100)}%` }}
                />
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
