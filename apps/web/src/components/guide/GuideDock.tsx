// 화면을 옮겨 다녀도 따라오는 단계 안내 창. 지금 할 일 하나와 눌러야 할 버튼을 보여 준다.
import { ArrowRight, Check, ChevronLeft, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { guideById } from "@/lib/guides";
import { useGuide } from "@/store/guide";

export function GuideDock() {
  const active = useGuide((s) => s.active);
  const go = useGuide((s) => s.go);
  const stop = useGuide((s) => s.stop);
  const navigate = useNavigate();
  const [finished, setFinished] = useState<string | null>(null);

  if (finished) {
    return (
      <section
        role="status"
        aria-label="가이드 끝"
        className="fixed bottom-4 left-3 z-40 w-[min(22rem,calc(100vw-6rem))] rounded-2xl border border-emerald-200 bg-white p-4 shadow-lift md:left-[17rem]"
      >
        <p className="flex items-center gap-1.5 text-sm font-semibold text-emerald-700">
          <Check className="h-4 w-4" /> 수고하셨어요! 끝까지 따라 했어요
        </p>
        <p className="mt-1 text-xs text-slate-500">&apos;{finished}&apos; 안내를 마쳤어요.</p>
        <div className="mt-3 flex justify-end">
          <Button size="sm" onClick={() => setFinished(null)}>
            닫기
          </Button>
        </div>
      </section>
    );
  }

  const guide = active ? guideById(active.id) : undefined;
  if (!active || !guide) return null;
  const step = guide.steps[active.step];
  if (!step) return null;
  const last = active.step === guide.steps.length - 1;

  return (
    <section
      aria-label={`가이드: ${guide.title}`}
      className="fixed bottom-4 left-3 z-40 w-[min(22rem,calc(100vw-6rem))] rounded-2xl border border-indigo-200 bg-white p-4 shadow-lift md:left-[17rem]"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-semibold text-indigo-600">
          {guide.emoji} {guide.title} · {active.step + 1}/{guide.steps.length}단계
        </p>
        <button
          type="button"
          aria-label="가이드 그만두기"
          title="그만두기"
          onClick={stop}
          className="rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-2 h-1 overflow-hidden rounded-full bg-slate-100" aria-hidden>
        <div
          className="h-full rounded-full bg-indigo-500 transition-all"
          style={{ width: `${((active.step + 1) / guide.steps.length) * 100}%` }}
        />
      </div>
      <h3 className="mt-3 text-sm font-bold text-slate-900">{step.title}</h3>
      <p className="mt-1 text-[13px] leading-relaxed text-slate-600">{step.body}</p>
      {step.action && (
        <Button size="sm" className="mt-3" onClick={() => step.action && navigate(step.action.to)}>
          {step.action.label} <ArrowRight className="h-3.5 w-3.5" />
        </Button>
      )}
      <div className="mt-3 flex items-center justify-between gap-2 border-t border-slate-100 pt-3">
        <button
          type="button"
          disabled={active.step === 0}
          onClick={() => go(active.step - 1)}
          className="inline-flex items-center gap-0.5 text-xs text-slate-500 hover:text-slate-800 disabled:opacity-30"
        >
          <ChevronLeft className="h-3.5 w-3.5" /> 이전
        </button>
        {last ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              const title = guide.title;
              stop();
              setFinished(title);
            }}
          >
            <Check className="h-3.5 w-3.5" /> 끝냈어요
          </Button>
        ) : (
          <Button size="sm" variant="outline" onClick={() => go(active.step + 1)}>
            했어요, 다음 <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
    </section>
  );
}
