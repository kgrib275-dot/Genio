import { CheckCircle2, ChevronDown, ChevronUp, Circle, GraduationCap, X } from "lucide-react";
import { useState } from "react";
import { LESSONS } from "@/help/learn";
import { cn } from "@/lib/cn";

const KEY = "genio.practice";

type Progress = Record<string, number[]>;

function load(): Progress {
  try {
    return JSON.parse(window.localStorage.getItem(KEY) || "{}") as Progress;
  } catch {
    return {};
  }
}

function save(p: Progress) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    /* 저장하지 못해도 이번 화면에서는 체크가 된다 */
  }
}

/** **굵게** 표시만 풀어서 보여 준다 */
function Rich({ text }: { text: string }) {
  return (
    <>
      {text
        .split(/(\*\*[^*]+\*\*)/g)
        .map((part, i) =>
          part.startsWith("**") ? <b key={i}>{part.slice(2, -2)}</b> : <span key={i}>{part}</span>,
        )}
    </>
  );
}

/** 빌더 화면 한쪽에 떠서 강좌의 다음 할 일을 알려 주는 실습 도우미(?lesson=강좌 id) */
export function PracticePanel({ lessonId, onClose }: { lessonId: string; onClose: () => void }) {
  const lesson = LESSONS.find((l) => l.id === lessonId);
  const [progress, setProgress] = useState<Progress>(load);
  const [open, setOpen] = useState(true);
  if (!lesson) return null;
  const done = progress[lesson.id] ?? [];
  const next = lesson.steps.findIndex((_, i) => !done.includes(i));
  const toggle = (i: number) => {
    const set = new Set(done);
    if (set.has(i)) set.delete(i);
    else set.add(i);
    const p = { ...progress, [lesson.id]: [...set].sort((a, b) => a - b) };
    setProgress(p);
    save(p);
  };
  const finished = done.length >= lesson.steps.length;

  return (
    <aside
      aria-label="실습 도우미"
      className="fixed right-4 top-40 z-30 w-[min(20rem,calc(100vw-2rem))] rounded-2xl border border-indigo-200 bg-white shadow-lift"
    >
      <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
        <GraduationCap className="h-4 w-4 text-indigo-600" />
        <p className="min-w-0 flex-1 truncate text-sm font-semibold">{lesson.title}</p>
        <span className="text-xs text-slate-500">
          {done.length}/{lesson.steps.length}
        </span>
        <button
          type="button"
          aria-label={open ? "접기" : "펼치기"}
          className="rounded p-1 text-slate-400 hover:bg-slate-100"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
        </button>
        <button
          type="button"
          aria-label="실습 끝내기"
          className="rounded p-1 text-slate-400 hover:bg-slate-100"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      {open && (
        <div className="max-h-[45vh] space-y-2 overflow-y-auto px-3 py-2.5">
          {finished ? (
            <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
              모든 단계를 해 봤어요! 이제 내 업무로 만들어 보세요.
            </p>
          ) : (
            <p className="text-xs text-slate-500">
              지금 할 일은 <b className="text-indigo-700">{next + 1}번</b>이에요. 했으면 눌러서
              체크하세요.
            </p>
          )}
          <ol className="space-y-1.5">
            {lesson.steps.map((s, i) => {
              const on = done.includes(i);
              return (
                <li key={i}>
                  <button
                    type="button"
                    aria-pressed={on}
                    onClick={() => toggle(i)}
                    className={cn(
                      "flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] leading-snug",
                      i === next ? "bg-indigo-50 ring-1 ring-indigo-200" : "hover:bg-slate-50",
                      on && "text-slate-400 line-through",
                    )}
                  >
                    {on ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                    ) : (
                      <Circle className="mt-0.5 h-4 w-4 shrink-0 text-slate-300" />
                    )}
                    <span>
                      <Rich text={s} />
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </aside>
  );
}
