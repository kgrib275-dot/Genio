// 챗 답변용 마크다운. HTML 원문은 그리지 않고(react-markdown 기본), 표·체크박스 등은 remark-gfm.
import { Check, Copy } from "lucide-react";
import { isValidElement, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn, copyText } from "@/lib/cn";

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return textOf(node.props.children);
  return "";
}

function CodeBlock({ children }: { children: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const code = textOf(children).replace(/\n$/, "");
  const child = Array.isArray(children) ? children[0] : children;
  const lang = isValidElement<{ className?: string }>(child)
    ? (/language-(\w+)/.exec(child.props.className ?? "")?.[1] ?? "")
    : "";
  return (
    <div className="group/code relative my-2 overflow-hidden rounded-lg border border-slate-200 bg-slate-900 text-slate-100">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-1 text-[11px] text-slate-400">
        <span>{lang || "코드"}</span>
        <button
          type="button"
          onClick={async () => {
            if (await copyText(code)) {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            }
          }}
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-white/10 hover:text-white"
          aria-label="코드 복사"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? "복사함" : "복사"}
        </button>
      </div>
      <pre className="overflow-x-auto px-3 py-2.5 font-mono text-[12.5px] leading-relaxed">
        {children}
      </pre>
    </div>
  );
}

const components: Components = {
  pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
  code: ({ className, children }) =>
    className ? (
      <code className={className}>{children}</code>
    ) : (
      <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.9em] text-rose-700">
        {children}
      </code>
    ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="font-medium text-[color:var(--chat-accent,#4f46e5)] underline underline-offset-2"
    >
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full border-collapse text-left text-[13px]">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border-b border-slate-200 bg-slate-50 px-2.5 py-1.5 font-semibold">
      {children}
    </th>
  ),
  td: ({ children }) => <td className="border-b border-slate-100 px-2.5 py-1.5">{children}</td>,
  ul: ({ children }) => <ul className="my-1.5 list-disc space-y-0.5 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="my-1.5 list-decimal space-y-0.5 pl-5">{children}</ol>,
  h1: ({ children }) => <h3 className="mb-1 mt-2 text-base font-bold">{children}</h3>,
  h2: ({ children }) => <h3 className="mb-1 mt-2 text-[15px] font-bold">{children}</h3>,
  h3: ({ children }) => <h4 className="mb-1 mt-2 font-semibold">{children}</h4>,
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-4 border-slate-200 pl-3 text-slate-600">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-3 border-slate-200" />,
  p: ({ children }) => <p className="my-1 first:mt-0 last:mb-0">{children}</p>,
};

export function Markdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cn("break-words leading-relaxed", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
