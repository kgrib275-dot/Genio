// v0.6 대시보드 '시작 체크리스트': 처음 할 일 몇 가지를 한 번에 누를 수 있게. 닫으면 다시 안 보인다(계정별).
import { CheckCircle2, ChevronDown, ChevronRight, Circle, Rocket, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { checklistItems, newlyDone, type ChecklistKey } from "@/components/onboarding/checklist";
import { findTarget } from "@/components/tour/tourSteps";
import { useMe } from "@/lib/api/auth";
import { useOnboardingStatus, useSaveOnboarding } from "@/lib/api/onboarding";
import { cn } from "@/lib/cn";
import { useSession } from "@/store/session";

function focusComposer() {
  const box = findTarget("composer");
  box?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  box?.querySelector<HTMLTextAreaElement>("textarea")?.focus();
}

export function StartChecklist({ firstAppId }: { firstAppId?: string }) {
  const { workspaceId: ws, role } = useSession();
  const me = useMe();
  const ob = me.data?.preferences?.onboarding;
  const dismissed = Boolean(ob?.checklist_dismissed);
  const status = useOnboardingStatus(ws, !dismissed);
  const save = useSaveOnboarding();
  const navigate = useNavigate();
  const [open, setOpen] = useState(true);
  const stepsDone = ob?.steps_done ?? [];
  const items = checklistItems(role, status.data, stepsDone);
  const fresh = newlyDone(items, stepsDone);
  const freshKey = fresh.join(",");

  // 새로 끝낸 일을 내 기록에 남긴다(앱을 지워도 체크가 풀리지 않게)
  useEffect(() => {
    if (freshKey && status.data) save.mutate({ steps_done: [...stepsDone, ...fresh] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [freshKey, status.data]);

  if (dismissed || items.length === 0 || !status.data) return null;
  const doneCount = items.filter((i) => i.done).length;
  const all = doneCount === items.length;

  const act = (key: ChecklistKey) => {
    switch (key) {
      case "ai":
        return navigate("/admin?tab=llm");
      case "samples":
        return navigate("/learn");
      case "app":
        return focusComposer();
      case "test":
        return firstAppId ? navigate(`/apps/${firstAppId}/builder`) : focusComposer();
      case "deploy":
        return firstAppId ? navigate(`/apps/${firstAppId}/settings`) : focusComposer();
      case "team":
        return navigate("/workspace");
    }
  };

  return (
    <section
      aria-label="시작 체크리스트"
      className="mb-6 rounded-2xl border border-emerald-100 bg-white p-4 shadow-card sm:p-5"
    >
      <div className="flex items-center gap-3">
        <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600">
          <Rocket className="h-5 w-5" />
        </span>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
        >
          <span className="font-semibold text-slate-900">
            {all ? "준비를 모두 마쳤어요!" : "시작 체크리스트"}
          </span>
          <span className="text-sm text-slate-500">
            {doneCount}/{items.length}
          </span>
          {open ? (
            <ChevronDown className="h-4 w-4 text-slate-400" />
          ) : (
            <ChevronRight className="h-4 w-4 text-slate-400" />
          )}
        </button>
        <button
          type="button"
          aria-label="체크리스트 닫기"
          title="닫기(다시 보이지 않아요)"
          onClick={() => save.mutate({ checklist_dismissed: true })}
          className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div
        className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100"
        role="progressbar"
        aria-label="체크리스트 진행"
        aria-valuemin={0}
        aria-valuemax={items.length}
        aria-valuenow={doneCount}
      >
        <div
          className="h-full rounded-full bg-emerald-500 transition-all"
          style={{ width: `${(doneCount / items.length) * 100}%` }}
        />
      </div>
      {open && (
        <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((it) => (
            <li key={it.key}>
              <button
                type="button"
                onClick={() => act(it.key)}
                className={cn(
                  "flex h-full w-full items-start gap-2.5 rounded-xl border px-3 py-2.5 text-left transition-colors",
                  it.done
                    ? "border-emerald-100 bg-emerald-50/60"
                    : "border-slate-200 hover:border-indigo-300 hover:bg-indigo-50/40",
                )}
              >
                {it.done ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                ) : (
                  <Circle className="mt-0.5 h-4 w-4 shrink-0 text-slate-300" />
                )}
                <span className="min-w-0">
                  <span
                    className={cn(
                      "block text-sm font-medium",
                      it.done
                        ? "text-emerald-800 line-through decoration-emerald-300"
                        : "text-slate-800",
                    )}
                  >
                    {it.title}
                  </span>
                  <span className="block text-xs text-slate-500">{it.hint}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
