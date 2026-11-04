import { Lightbulb } from "lucide-react";
import type { ReactNode } from "react";
import type { HelpBlock, HelpSection } from "@/help/content";

/** **굵게**, `코드`만 처리하는 작은 렌더러 */
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**"))
      out.push(
        <strong key={i++} className="font-semibold text-slate-900">
          {tok.slice(2, -2)}
        </strong>,
      );
    else
      out.push(
        <code key={i++} className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.85em]">
          {tok.slice(1, -1)}
        </code>,
      );
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function Block({ block }: { block: HelpBlock }) {
  switch (block.type) {
    case "p":
      return <p className="leading-relaxed">{inline(block.text)}</p>;
    case "tip":
      return (
        <p className="flex gap-2 rounded-lg bg-amber-50 px-3 py-2 leading-relaxed text-amber-900">
          <Lightbulb className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{inline(block.text)}</span>
        </p>
      );
    case "steps":
      return (
        <ol className="list-decimal space-y-1 pl-5 leading-relaxed marker:text-indigo-500">
          {block.items.map((t, i) => (
            <li key={i}>{inline(t)}</li>
          ))}
        </ol>
      );
    case "list":
      return (
        <ul className="list-disc space-y-1 pl-5 leading-relaxed marker:text-slate-300">
          {block.items.map((t, i) => (
            <li key={i}>{inline(t)}</li>
          ))}
        </ul>
      );
  }
}

export function HelpSectionView({
  section,
  heading = true,
}: {
  section: HelpSection;
  heading?: boolean;
}) {
  return (
    <section id={section.id} className="scroll-mt-20 space-y-3 text-sm text-slate-700">
      {heading && (
        <h2 className="text-lg font-bold tracking-tight text-slate-900">{section.title}</h2>
      )}
      <p className="border-l-2 border-indigo-200 pl-3 text-[0.95rem] text-slate-600">
        {section.summary}
      </p>
      {section.blocks.map((b, i) => (
        <Block key={i} block={b} />
      ))}
    </section>
  );
}
