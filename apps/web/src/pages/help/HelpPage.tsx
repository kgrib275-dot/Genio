import { BookMarked } from "lucide-react";
import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { ListToolbar, NoMatch } from "@/components/ListControls";
import { HELP_SECTIONS, type HelpSection } from "@/help/content";
import { HelpSectionView } from "@/help/HelpView";
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
  // 사용설명서는 단락 수가 적어 페이지를 나누지 않고 검색만 한다
  const c = useListControls(HELP_SECTIONS, { key: "help", defaultSize: 100, search: sectionText });
  const shown = c.filtered;
  useEffect(() => {
    if (!hash) return;
    const el = document.getElementById(hash.slice(1));
    el?.scrollIntoView?.({ block: "start" });
  }, [hash]);

  return (
    <PageContainer>
      <div className="mb-6 flex flex-wrap items-center gap-x-4 gap-y-3">
        <div className="flex items-center gap-2">
          <BookMarked className="h-6 w-6 text-indigo-500" />
          <h1 className="text-xl font-bold tracking-tight sm:text-2xl">사용설명서</h1>
        </div>
        <ListToolbar c={c} placeholder="궁금한 것 찾기 (예: 배포, 비밀번호)" className="flex-1" />
      </div>
      <div className="grid gap-8 lg:grid-cols-[220px_1fr]">
        <nav aria-label="목차" className="lg:sticky lg:top-6 lg:self-start">
          <ol className="flex gap-1 overflow-x-auto pb-1 text-sm lg:flex-col lg:overflow-visible">
            {shown.map((s) => (
              <li key={s.id} className="shrink-0">
                <a
                  href={`#${s.id}`}
                  className="block whitespace-nowrap rounded-lg px-3 py-1.5 text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                >
                  <span className="mr-1.5 text-xs text-slate-400">
                    {HELP_SECTIONS.indexOf(s) + 1}
                  </span>
                  {s.title}
                </a>
              </li>
            ))}
          </ol>
        </nav>
        <div className="space-y-10 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-card sm:p-8">
          <NoMatch c={c} />
          {shown.map((s) => (
            <HelpSectionView key={s.id} section={s} />
          ))}
        </div>
      </div>
    </PageContainer>
  );
}
