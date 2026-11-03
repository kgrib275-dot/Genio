import { BookMarked } from "lucide-react";
import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { HELP_SECTIONS } from "@/help/content";
import { HelpSectionView } from "@/help/HelpView";

export default function HelpPage() {
  const { hash } = useLocation();
  useEffect(() => {
    if (!hash) return;
    const el = document.getElementById(hash.slice(1));
    el?.scrollIntoView?.({ block: "start" });
  }, [hash]);

  return (
    <PageContainer>
      <div className="mb-6 flex items-center gap-2">
        <BookMarked className="h-6 w-6 text-indigo-500" />
        <h1 className="text-xl font-bold tracking-tight sm:text-2xl">사용설명서</h1>
      </div>
      <div className="grid gap-8 lg:grid-cols-[220px_1fr]">
        <nav aria-label="목차" className="lg:sticky lg:top-6 lg:self-start">
          <ol className="flex gap-1 overflow-x-auto pb-1 text-sm lg:flex-col lg:overflow-visible">
            {HELP_SECTIONS.map((s, i) => (
              <li key={s.id} className="shrink-0">
                <a
                  href={`#${s.id}`}
                  className="block whitespace-nowrap rounded-lg px-3 py-1.5 text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                >
                  <span className="mr-1.5 text-xs text-slate-400">{i + 1}</span>
                  {s.title}
                </a>
              </li>
            ))}
          </ol>
        </nav>
        <div className="space-y-10 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-card sm:p-8">
          {HELP_SECTIONS.map((s) => (
            <HelpSectionView key={s.id} section={s} />
          ))}
        </div>
      </div>
    </PageContainer>
  );
}
