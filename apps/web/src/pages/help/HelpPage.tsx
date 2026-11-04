import { ArrowUp, BookMarked, GraduationCap } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { ListToolbar, NoMatch } from "@/components/ListControls";
import { HELP_SECTIONS, type HelpSection } from "@/help/content";
import { HelpSectionView } from "@/help/HelpView";
import { cn } from "@/lib/cn";
import { useListControls } from "@/lib/useListControls";

/** 단락 제목·요약·본문을 이어 붙인 검색용 글 */
function sectionText(s: HelpSection): string {
  const body = s.blocks
    .map((b) => ("text" in b ? b.text : b.items.join(" ")))
    .join(" ")
    .replace(/\*\*|`/g, "");
  return `${s.title} ${s.summary} ${body}`;
}

export default function HelpPage() {
  const { hash } = useLocation();
  const navigate = useNavigate();
  // 사용설명서는 단락 수가 적어 페이지를 나누지 않고 검색만 한다
  const c = useListControls(HELP_SECTIONS, { key: "help", defaultSize: 100, search: sectionText });
  const shown = c.filtered;
  const [current, setCurrent] = useState<string>(HELP_SECTIONS[0]?.id ?? "");

  useEffect(() => {
    if (!hash) return;
    const el = document.getElementById(hash.slice(1));
    el?.scrollIntoView?.({ block: "start" });
    setCurrent(hash.slice(1));
  }, [hash]);

  // 지금 읽는 단락을 목차에 표시한다
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const obs = new IntersectionObserver(
      (entries) => {
        const top = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (top) setCurrent(top.target.id);
      },
      { rootMargin: "-80px 0px -60% 0px" },
    );
    for (const s of shown) {
      const el = document.getElementById(s.id);
      if (el) obs.observe(el);
    }
    return () => obs.disconnect();
  }, [shown]);

  return (
    <PageContainer>
      <div className="mb-6 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <BookMarked className="h-6 w-6 text-indigo-500" />
            <h1 className="text-xl font-bold tracking-tight sm:text-2xl">사용설명서</h1>
          </div>
          <Link
            to="/learn"
            className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-sm font-medium text-indigo-700 hover:bg-indigo-100"
          >
            <GraduationCap className="h-4 w-4" /> 처음이면 배우기부터
          </Link>
        </div>
        <ListToolbar c={c} placeholder="궁금한 것 찾기 (예: 병렬, 배포, 비밀번호)" />
        {/* 휴대폰: 목차를 고르는 칸 */}
        <label className="block lg:hidden">
          <span className="sr-only">목차</span>
          <select
            aria-label="목차"
            value={current}
            onChange={(e) => {
              setCurrent(e.target.value);
              navigate(`#${e.target.value}`);
            }}
            className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-800"
          >
            {shown.map((s) => (
              <option key={s.id} value={s.id}>
                {HELP_SECTIONS.indexOf(s) + 1}. {s.title}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="grid gap-8 lg:grid-cols-[230px_1fr]">
        <nav aria-label="목차" className="hidden lg:sticky lg:top-6 lg:block lg:self-start">
          <p className="mb-2 px-3 text-xs font-semibold text-slate-400">목차</p>
          <ol className="max-h-[calc(100vh-8rem)] space-y-0.5 overflow-y-auto text-sm">
            {shown.map((s) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className={cn(
                    "flex items-center gap-2 rounded-lg px-3 py-1.5 transition-colors",
                    current === s.id
                      ? "bg-indigo-50 font-semibold text-indigo-700"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                  )}
                >
                  <span
                    className={cn(
                      "inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px]",
                      current === s.id ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-500",
                    )}
                  >
                    {HELP_SECTIONS.indexOf(s) + 1}
                  </span>
                  <span className="truncate">{s.title}</span>
                </a>
              </li>
            ))}
          </ol>
        </nav>
        <div className="min-w-0 space-y-5">
          <NoMatch c={c} />
          {shown.map((s) => (
            <article
              key={s.id}
              className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-card sm:p-7"
            >
              <div className="mb-1 text-xs font-semibold text-indigo-500">
                {HELP_SECTIONS.indexOf(s) + 1} / {HELP_SECTIONS.length}
              </div>
              <HelpSectionView section={s} />
            </article>
          ))}
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => window.scrollTo?.({ top: 0, behavior: "smooth" })}
              className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100"
            >
              <ArrowUp className="h-4 w-4" /> 맨 위로
            </button>
          </div>
        </div>
      </div>
    </PageContainer>
  );
}
