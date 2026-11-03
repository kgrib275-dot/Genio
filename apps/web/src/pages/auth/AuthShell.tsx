import { Bot, FileText, GitBranch, MessageSquare, Search, Send, Sparkles } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { ko } from "@/i18n/ko";
import { cn } from "@/lib/cn";

// 로그인·가입·초대 화면이 함께 쓰는 틀.
// 넓은 화면: 왼쪽에 "말로 요청 → 흐름이 그려지는" 짧은 시연, 오른쪽에 입력 카드.
// 좁은 화면: 로고와 입력 카드만.

type Step = { label: string; icon: typeof Bot; tone: string };

const SCENARIOS: { prompt: string; steps: Step[] }[] = [
  {
    prompt: "고객 문의 메일을 분류해서 담당 팀에 알려 줘",
    steps: [
      { label: "문의 받기", icon: MessageSquare, tone: "bg-sky-500" },
      { label: "AI로 분류", icon: Bot, tone: "bg-violet-500" },
      { label: "팀별로 나누기", icon: GitBranch, tone: "bg-amber-500" },
      { label: "슬랙 알림", icon: Send, tone: "bg-emerald-500" },
    ],
  },
  {
    prompt: "사내 규정 문서로 질문에 답하는 챗봇 만들어 줘",
    steps: [
      { label: "질문 받기", icon: MessageSquare, tone: "bg-sky-500" },
      { label: "규정 문서 검색", icon: Search, tone: "bg-indigo-500" },
      { label: "AI 답변", icon: Bot, tone: "bg-violet-500" },
      { label: "출처와 함께 답하기", icon: FileText, tone: "bg-emerald-500" },
    ],
  },
  {
    prompt: "회의록을 요약해서 할 일만 뽑아 줘",
    steps: [
      { label: "회의록 올리기", icon: FileText, tone: "bg-sky-500" },
      { label: "AI 요약", icon: Bot, tone: "bg-violet-500" },
      { label: "할 일 뽑기", icon: Sparkles, tone: "bg-amber-500" },
      { label: "메일로 보내기", icon: Send, tone: "bg-emerald-500" },
    ],
  },
];

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/** 요청 문장을 한 글자씩 치고, 흐름 블록을 하나씩 띄우는 시연. 끝나면 다음 예시로. */
function BuilderDemo() {
  const [idx, setIdx] = useState(0);
  const [typed, setTyped] = useState(0);
  const [shown, setShown] = useState(0);
  const sc = SCENARIOS[idx % SCENARIOS.length] as (typeof SCENARIOS)[number];

  useEffect(() => {
    if (prefersReducedMotion()) {
      setTyped(sc.prompt.length);
      setShown(sc.steps.length);
      return;
    }
    let cancelled = false;
    const timers: number[] = [];
    const at = (ms: number, fn: () => void) =>
      timers.push(window.setTimeout(() => !cancelled && fn(), ms));
    setTyped(0);
    setShown(0);
    let t = 300;
    for (let i = 1; i <= sc.prompt.length; i++) {
      at(t, () => setTyped(i));
      t += 55;
    }
    t += 450;
    for (let i = 1; i <= sc.steps.length; i++) {
      at(t, () => setShown(i));
      t += 420;
    }
    at(t + 2600, () => setIdx((v) => (v + 1) % SCENARIOS.length));
    return () => {
      cancelled = true;
      timers.forEach((x) => window.clearTimeout(x));
    };
  }, [idx, sc]);

  const done = shown === sc.steps.length;
  return (
    <div className="w-full max-w-sm" aria-hidden>
      {/* 요청 말풍선 */}
      <div className="ml-auto w-fit max-w-[90%] rounded-2xl rounded-br-md bg-white/15 px-4 py-3 text-[15px] leading-relaxed text-white shadow-lg ring-1 ring-white/20 backdrop-blur">
        {sc.prompt.slice(0, typed)}
        {typed < sc.prompt.length && (
          <span className="genio-caret ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 bg-white" />
        )}
      </div>
      {/* 빌더 답 */}
      <div
        className={cn(
          "mt-3 flex items-center gap-2 text-xs text-indigo-100 transition-opacity duration-300",
          typed === sc.prompt.length ? "opacity-100" : "opacity-0",
        )}
      >
        <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-white/20">
          <Sparkles className="h-3.5 w-3.5" />
        </span>
        {done ? "흐름을 만들었어요. 바로 테스트해 볼 수 있어요." : "흐름을 그리는 중…"}
      </div>
      {/* 흐름 블록 */}
      <ol className="relative mt-4 space-y-2.5 pl-1">
        {sc.steps.map((s, i) => {
          const Icon = s.icon;
          const on = i < shown;
          return (
            <li
              key={`${idx}-${s.label}`}
              className={cn(
                "relative flex items-center gap-3 rounded-xl bg-white px-3 py-2.5 text-sm font-medium text-slate-800 shadow-lg transition-all duration-500",
                on ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0",
              )}
            >
              {i > 0 && (
                <span
                  className={cn(
                    "absolute -top-2.5 left-[26px] h-2.5 w-0.5 bg-white/60 transition-opacity duration-500",
                    on ? "opacity-100" : "opacity-0",
                  )}
                />
              )}
              <span
                className={cn(
                  "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-white",
                  s.tone,
                )}
              >
                <Icon className="h-4 w-4" />
              </span>
              {s.label}
              {on && i === shown - 1 && !done && (
                <span className="ml-auto h-2 w-2 animate-ping rounded-full bg-indigo-400" />
              )}
            </li>
          );
        })}
      </ol>
      {/* 예시 표시 점 */}
      <div className="mt-6 flex gap-1.5">
        {SCENARIOS.map((_, i) => (
          <span
            key={i}
            className={cn(
              "h-1.5 rounded-full transition-all duration-500",
              i === idx ? "w-6 bg-white" : "w-1.5 bg-white/40",
            )}
          />
        ))}
      </div>
    </div>
  );
}

function LogoMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 font-bold text-white shadow-md",
        className,
      )}
    >
      G
    </span>
  );
}

export function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-slate-50">
      {/* 왼쪽: 소개와 시연(넓은 화면) */}
      <aside className="relative hidden w-[46%] max-w-[640px] overflow-hidden bg-gradient-to-br from-indigo-600 via-indigo-700 to-violet-800 lg:flex lg:flex-col lg:justify-between lg:p-12">
        <span className="genio-blob absolute -left-24 -top-24 h-80 w-80 rounded-full bg-violet-400/30 blur-3xl" />
        <span className="genio-blob genio-blob-delay absolute -bottom-32 right-[-80px] h-96 w-96 rounded-full bg-sky-400/25 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <LogoMark className="h-10 w-10 bg-none bg-white/15 text-lg ring-1 ring-white/30" />
          <div className="leading-tight text-white">
            <p className="text-lg font-bold">{ko.appName}</p>
            <p className="text-xs text-indigo-100">{ko.tagline}</p>
          </div>
        </div>
        <div className="relative">
          <h2 className="mb-8 text-3xl font-bold leading-snug tracking-tight text-white">
            말로 요청하면
            <br />
            일하는 앱이 만들어져요.
          </h2>
          <BuilderDemo />
        </div>
        <p className="relative text-xs text-indigo-200">
          만들고 · 다듬고 · 챗봇으로 배포까지, 10분이면 충분해요.
        </p>
      </aside>

      {/* 오른쪽: 입력 카드 */}
      <main className="relative flex flex-1 items-center justify-center px-4 py-10">
        <span className="genio-blob pointer-events-none absolute right-10 top-10 h-56 w-56 rounded-full bg-indigo-200/40 blur-3xl lg:hidden" />
        <div className="genio-rise relative w-full max-w-sm">
          <div className="mb-6 flex flex-col items-center text-center lg:hidden">
            <LogoMark className="h-12 w-12 text-xl" />
            <p className="mt-3 text-2xl font-bold text-slate-900">{ko.appName}</p>
            <p className="text-sm text-slate-500">{ko.tagline}</p>
          </div>
          <div className="mb-5 text-center lg:text-left">
            <h1 className="text-xl font-bold tracking-tight text-slate-900 lg:text-2xl">{title}</h1>
            {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
          </div>
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-lift sm:p-7">
            {children}
          </div>
        </div>
      </main>
    </div>
  );
}
