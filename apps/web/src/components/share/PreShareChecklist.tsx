import { CheckCircle2, Circle } from "lucide-react";
import { Link } from "react-router-dom";
import { useAppRuns } from "@/lib/api/apps";
import { useEvalGate, useEvalHistory } from "@/lib/api/evals";
import { normalizeFeatures, type AppFeatures } from "@/lib/api/types";

interface Item {
  ok: boolean;
  text: string;
  hint?: string;
  to?: string;
}

/** 공유하기 전에 확인할 것을 한 화면에 모아 보여 준다(막지는 않고 알려만 준다). */
export function PreShareChecklist({
  appId,
  features,
}: {
  appId: string;
  features?: Partial<AppFeatures> | null;
}) {
  const runs = useAppRuns(appId);
  const gate = useEvalGate(appId);
  const history = useEvalHistory(appId);
  const f = normalizeFeatures(features);
  const tested = (runs.data ?? []).length > 0;
  const latest = (history.data?.batches ?? []).find((b) => !b.running);
  const items: Item[] = [
    {
      ok: tested,
      text: tested ? "직접 한 번 써 봤어요" : "아직 한 번도 써 보지 않았어요",
      hint: "만들기 화면의 '대화로 시험'으로 질문해 보세요.",
      to: `/apps/${appId}/builder`,
    },
    {
      ok: f.ai_notice.enabled,
      text: f.ai_notice.enabled
        ? "'AI가 답해요' 안내가 켜져 있어요"
        : "'AI가 답해요' 안내가 꺼져 있어요",
      hint: "AI 기본법상 이용자에게 알려야 해서 켜 두기를 권해요.",
      to: `/apps/${appId}/features`,
    },
    {
      ok: !f.maintenance.enabled,
      text: f.maintenance.enabled
        ? "지금 '점검 중' 표시가 켜져 있어요"
        : "점검 중 표시가 꺼져 있어요",
      hint: "켜져 있으면 공유한 사람이 쓸 수 없어요.",
      to: `/apps/${appId}/features`,
    },
    {
      ok: Boolean(latest) || !(gate.data?.enabled ?? false),
      text: latest
        ? `최근 품질 점검 통과율 ${Math.round((latest.pass_rate ?? 0) * 100)}%`
        : gate.data?.enabled
          ? "품질 점검을 아직 하지 않았어요(배포 조건이 켜져 있어요)"
          : "품질 점검은 선택이에요",
      hint: "자주 오는 질문을 저장해 두고 점검해 보세요.",
      to: `/apps/${appId}/evals`,
    },
  ];
  return (
    <section
      aria-label="공유 전 점검표"
      className="rounded-xl border border-slate-200 bg-slate-50 p-3"
    >
      <p className="mb-1.5 text-sm font-semibold text-slate-800">공유하기 전에 확인해 보세요</p>
      <ul className="space-y-1">
        {items.map((it) => (
          <li key={it.text} className="flex items-start gap-2 text-[13px]">
            {it.ok ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
            ) : (
              <Circle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
            )}
            <span className={it.ok ? "text-slate-600" : "text-slate-900"}>
              {it.text}
              {!it.ok && it.to && (
                <>
                  {" — "}
                  <Link to={it.to} className="text-indigo-600 hover:underline">
                    {it.hint ?? "확인하러 가기"}
                  </Link>
                </>
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
