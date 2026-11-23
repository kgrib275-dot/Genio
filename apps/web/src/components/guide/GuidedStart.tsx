// 대시보드의 "무엇을 하고 싶으세요?" 카드: 목표를 고르면 단계별 안내가 시작된다.
import { ChevronDown, ChevronUp, Compass } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { guideById, guidesFor } from "@/lib/guides";
import { useGuide } from "@/store/guide";
import { useSession } from "@/store/session";

const KEY = "genio.guideStartOpen";

function loadOpen(): boolean {
  try {
    return window.localStorage.getItem(KEY) !== "0";
  } catch {
    return true;
  }
}

export function GuidedStart() {
  const role = useSession((s) => s.role);
  const active = useGuide((s) => s.active);
  const start = useGuide((s) => s.start);
  const navigate = useNavigate();
  const [open, setOpen] = useState(loadOpen);
  const guides = guidesFor(role);
  if (guides.length === 0) return null;

  const toggle = () => {
    setOpen((v) => {
      try {
        window.localStorage.setItem(KEY, v ? "0" : "1");
      } catch {
        // 저장하지 못해도 이번 화면에서는 적용된다.
      }
      return !v;
    });
  };
  const running = active ? guideById(active.id) : undefined;

  return (
    <section
      aria-label="처음이라면 안내를 따라 해 보세요"
      className="mt-6 rounded-2xl border border-indigo-100 bg-indigo-50/60 p-4 sm:p-5"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-bold text-slate-900">
          <Compass className="h-4 w-4 text-indigo-600" /> 무엇을 하고 싶으세요? 안내를 따라 해
          보세요
        </h2>
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          className="inline-flex items-center gap-0.5 text-xs text-slate-500 hover:text-slate-800"
        >
          {open ? (
            <>
              접기 <ChevronUp className="h-3.5 w-3.5" />
            </>
          ) : (
            <>
              펼치기 <ChevronDown className="h-3.5 w-3.5" />
            </>
          )}
        </button>
      </div>
      {open && (
        <>
          <p className="mt-1 text-xs text-slate-500">
            고르면 한 단계씩 어디를 눌러야 하는지 알려 줘요. 화면을 옮겨 다녀도 안내가 따라와요.
          </p>
          {running && (
            <p role="note" className="mt-2 rounded-md bg-white px-3 py-1.5 text-xs text-indigo-700">
              지금 &apos;{running.title}&apos; 안내를 진행 중이에요(화면 왼쪽 아래).
            </p>
          )}
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {guides.map((g) => (
              <button
                key={g.id}
                type="button"
                onClick={() => {
                  start(g.id);
                  const first = g.steps[0]?.action;
                  if (first) navigate(first.to);
                }}
                className="flex flex-col items-start gap-1 rounded-xl border border-slate-200 bg-white p-3 text-left transition-colors hover:border-indigo-300 hover:shadow-card"
              >
                <span className="text-lg" aria-hidden>
                  {g.emoji}
                </span>
                <span className="text-sm font-semibold text-slate-800">{g.title}</span>
                <span className="text-xs leading-relaxed text-slate-500">{g.summary}</span>
                <span className="mt-1 text-[11px] text-indigo-600">{g.steps.length}단계</span>
              </button>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
