// v0.6 첫 로그인 화면 투어: 화면 요소를 밝게 짚고(스포트라이트) 설명 카드를 띄운다.
// 새 라이브러리 없이 만들었다. 키보드: → / Enter 다음, ← 이전, Esc 건너뛰기.
import { X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { findTarget, type TourStep } from "@/components/tour/tourSteps";

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

const PAD = 6;
const CARD_W = 320;

function placeCard(rect: Rect | null): React.CSSProperties {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const width = Math.min(CARD_W, vw - 24);
  if (!rect) return { width, left: (vw - width) / 2, top: Math.max(24, vh / 2 - 110) };
  // 오른쪽 자리가 넉넉하면 오른쪽, 아니면 아래, 그것도 안 되면 위
  if (rect.left + rect.width + width + 24 < vw && rect.height < vh - 40) {
    return {
      width,
      left: rect.left + rect.width + 16,
      top: Math.min(Math.max(12, rect.top), vh - 240),
    };
  }
  const left = Math.min(Math.max(12, rect.left), vw - width - 12);
  if (rect.top + rect.height + 230 < vh) return { width, left, top: rect.top + rect.height + 14 };
  return { width, left, top: Math.max(12, rect.top - 230) };
}

export function GuidedTour({
  steps,
  onClose,
}: {
  steps: TourStep[];
  /** done=true면 끝까지 봄, false면 건너뜀 */
  onClose: (done: boolean) => void;
}) {
  const [i, setI] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const step = steps[i];

  const measure = useCallback(() => {
    if (!step) return;
    const el = findTarget(step.target);
    if (!el) {
      setRect(null);
      return;
    }
    const r = el.getBoundingClientRect();
    setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
  }, [step]);

  useLayoutEffect(() => {
    const el = step ? findTarget(step.target) : null;
    el?.scrollIntoView?.({ block: "nearest" });
    measure();
  }, [step, measure]);

  useEffect(() => {
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [measure]);

  useEffect(() => {
    cardRef.current?.focus();
  }, [i]);

  const next = useCallback(() => {
    if (i >= steps.length - 1) onClose(true);
    else setI(i + 1);
  }, [i, steps.length, onClose]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose(false);
      else if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") setI((v) => Math.max(0, v - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, onClose]);

  if (!step) return null;
  const last = i === steps.length - 1;
  return (
    <div className="fixed inset-0 z-[60]" role="presentation">
      {rect ? (
        <div
          aria-hidden
          className="pointer-events-none fixed rounded-xl ring-2 ring-indigo-400 transition-all duration-200"
          style={{
            top: rect.top - PAD,
            left: rect.left - PAD,
            width: rect.width + PAD * 2,
            height: rect.height + PAD * 2,
            boxShadow: "0 0 0 9999px rgba(2, 6, 23, 0.55)",
          }}
        />
      ) : (
        <div aria-hidden className="fixed inset-0" style={{ background: "rgba(2, 6, 23, 0.55)" }} />
      )}
      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-body"
        tabIndex={-1}
        className="fixed rounded-2xl border border-slate-200 bg-white p-4 text-slate-800 shadow-xl outline-none"
        style={placeCard(rect)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && e.target === cardRef.current) next();
        }}
      >
        <div className="flex items-start justify-between gap-2">
          <p className="text-xs font-semibold text-indigo-600">
            {i + 1} / {steps.length}
          </p>
          <button
            type="button"
            aria-label="안내 닫기"
            onClick={() => onClose(false)}
            className="-m-1 rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <h2 id="tour-title" className="mt-1 text-base font-bold text-slate-900">
          {step.title}
        </h2>
        <p id="tour-body" className="mt-1 text-sm leading-relaxed text-slate-600">
          {step.body}
        </p>
        <div className="mt-4 flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => onClose(false)}
            className="text-xs text-slate-500 hover:text-slate-800"
          >
            건너뛰기
          </button>
          <div className="flex gap-2">
            {i > 0 && (
              <Button size="sm" variant="outline" onClick={() => setI(i - 1)}>
                이전
              </Button>
            )}
            <Button size="sm" onClick={next}>
              {last ? "시작하기" : "다음"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
