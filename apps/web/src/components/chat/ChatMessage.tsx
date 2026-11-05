import {
  BookMarked,
  Check,
  ChevronDown,
  Copy,
  Image as ImageIcon,
  Paperclip,
  RotateCcw,
  ShieldBan,
  ThumbsDown,
  ThumbsUp,
  Volume2,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { AppIcon } from "@/components/AppIcon";
import { Markdown } from "@/components/chat/Markdown";
import { FileList, type ResolveFile } from "@/components/files/FileList";
import { KbImage } from "@/components/knowledge/KbImage";
import type { CitationImage } from "@/lib/api/kbcanvas";
import type { ChatLine } from "@/lib/api/chat";
import type { Citation, Rating } from "@/lib/api/types";
import { cn, copyText } from "@/lib/cn";

type CitationWithImage = Citation & { image?: CitationImage };

function Citations({ items }: { items: CitationWithImage[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="mt-2 space-y-1">
      <p className="flex items-center gap-1 text-[11px] font-medium text-slate-400">
        <BookMarked className="h-3 w-3" /> 출처
      </p>
      <div className="flex flex-wrap gap-1">
        {items.map((c) => (
          <button
            key={c.index}
            type="button"
            onClick={() => setOpen(open === c.index ? null : c.index)}
            aria-expanded={open === c.index}
            className={cn(
              "inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]",
              open === c.index
                ? "border-indigo-300 bg-indigo-50 text-indigo-700"
                : "border-slate-200 bg-white text-slate-600 hover:border-slate-300",
            )}
          >
            <span className="font-semibold">{c.index}</span>
            <span className="truncate">{c.filename}</span>
            {c.image && <ImageIcon className="h-3 w-3 shrink-0" aria-label="그림 있음" />}
            <ChevronDown className={cn("h-3 w-3 shrink-0", open === c.index && "rotate-180")} />
          </button>
        ))}
      </div>
      {items
        .filter((c) => c.index === open)
        .map((c) => (
          <div
            key={c.index}
            className="max-h-64 space-y-2 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600"
          >
            {c.image && <KbImage image={c.image} />}
            <p className="whitespace-pre-wrap">{c.content}</p>
          </div>
        ))}
    </div>
  );
}

function ActionButton({
  label,
  onClick,
  pressed,
  className,
  children,
}: {
  label: string;
  onClick: () => void;
  pressed?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      onClick={onClick}
      className={cn("rounded-md p-1 hover:bg-slate-100 hover:text-slate-700", className)}
    >
      {children}
    </button>
  );
}

const timeOf = (iso?: string) =>
  iso ? new Date(iso).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" }) : "";

export function ChatMessage({
  line,
  appName,
  appIcon,
  isLast,
  busy,
  canRate,
  canSpeak,
  onRate,
  onRegenerate,
  onRetry,
  onSuggest,
  onSpeak,
  resolveFile,
}: {
  line: ChatLine;
  appName: string;
  appIcon?: string;
  isLast: boolean;
  busy: boolean;
  canRate: boolean;
  canSpeak: boolean;
  onRate: (line: ChatLine, rating: Rating) => void;
  onRegenerate: () => void;
  onRetry: () => void;
  onSuggest: (q: string) => void;
  onSpeak: (text: string) => void;
  /** 이미지·파일 단계가 만든 파일을 받을 경로 */
  resolveFile?: ResolveFile;
}) {
  const [copied, setCopied] = useState(false);

  if (line.role === "user")
    return (
      <div className="flex justify-end" title={timeOf(line.createdAt)}>
        <div className="max-w-[85%] sm:max-w-[75%]">
          <div className="whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-[color:var(--chat-accent)] px-3.5 py-2 text-[15px] leading-relaxed text-white shadow-sm sm:text-sm">
            {line.text}
          </div>
          {line.files && line.files.length > 0 && (
            <div className="mt-1 flex flex-wrap justify-end gap-1">
              {line.files.map((f) => (
                <span
                  key={f.id}
                  className="inline-flex max-w-full items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600"
                >
                  <Paperclip className="h-3 w-3 shrink-0" />
                  <span className="truncate">{f.filename}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    );

  if (line.role === "error")
    return (
      <div role="alert" className="flex justify-start">
        <div className="max-w-[90%] rounded-2xl border border-red-200 bg-red-50 px-3.5 py-2.5 text-sm">
          <p className="font-medium text-red-900">{line.text}</p>
          {line.hint && <p className="mt-0.5 text-xs text-red-700">{line.hint}</p>}
          {isLast && !busy && (
            <button
              type="button"
              onClick={onRetry}
              className="mt-2 inline-flex items-center gap-1 rounded-lg border border-red-200 bg-white px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
            >
              <RotateCcw className="h-3 w-3" /> 다시 시도
            </button>
          )}
        </div>
      </div>
    );

  const waiting = line.streaming && !line.text;
  return (
    <div className="flex items-start gap-2" title={timeOf(line.createdAt)}>
      <span className="mt-0.5 hidden sm:block">
        <AppIcon name={appName} icon={appIcon} size="sm" />
      </span>
      <div className="min-w-0 max-w-full flex-1 sm:max-w-[85%] sm:flex-none">
        {line.agent && <p className="mb-1 text-[11px] font-semibold text-emerald-700">상담원</p>}
        <div
          className={cn(
            "rounded-2xl rounded-tl-md border px-3.5 py-2.5 text-[15px] text-slate-900 shadow-sm sm:text-sm",
            line.agent ? "border-emerald-200 bg-emerald-50" : "border-slate-200 bg-white",
          )}
        >
          {waiting ? (
            <span className="flex items-center gap-1 py-1" aria-label="답을 쓰는 중">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:120ms]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:240ms]" />
            </span>
          ) : (
            <Markdown text={line.streaming ? `${line.text}▍` : line.text} />
          )}
          {line.stopped && <p className="mt-1 text-[11px] text-slate-400">답을 멈췄어요.</p>}
        </div>
        {!line.streaming && (
          <>
            {resolveFile && line.outFiles && line.outFiles.length > 0 && (
              <FileList files={line.outFiles} resolve={resolveFile} className="mt-2" />
            )}
            {line.citations && line.citations.length > 0 && <Citations items={line.citations} />}
            <div className="mt-1 flex flex-wrap items-center gap-0.5 text-slate-400">
              {line.moderated && (
                <span className="mr-1 inline-flex items-center gap-0.5 text-[11px]">
                  <ShieldBan className="h-3 w-3" /> 정해진 답
                </span>
              )}
              {line.annotated && <span className="mr-1 text-[11px]">등록된 답</span>}
              <ActionButton
                label={copied ? "복사했어요" : "답 복사"}
                onClick={async () => {
                  if (await copyText(line.text)) {
                    setCopied(true);
                    window.setTimeout(() => setCopied(false), 1500);
                  }
                }}
              >
                {copied ? (
                  <Check className="h-3.5 w-3.5 text-emerald-600" />
                ) : (
                  <Copy className="h-3.5 w-3.5" />
                )}
              </ActionButton>
              {isLast && !busy && (
                <ActionButton label="다시 답하기" onClick={onRegenerate}>
                  <RotateCcw className="h-3.5 w-3.5" />
                </ActionButton>
              )}
              {canRate && line.messageId && (
                <>
                  <ActionButton
                    label="좋아요"
                    pressed={line.rating === "like"}
                    onClick={() => onRate(line, "like")}
                    className={cn(line.rating === "like" && "text-emerald-600")}
                  >
                    <ThumbsUp className="h-3.5 w-3.5" />
                  </ActionButton>
                  <ActionButton
                    label="싫어요"
                    pressed={line.rating === "dislike"}
                    onClick={() => onRate(line, "dislike")}
                    className={cn(line.rating === "dislike" && "text-red-600")}
                  >
                    <ThumbsDown className="h-3.5 w-3.5" />
                  </ActionButton>
                </>
              )}
              {canSpeak && (
                <ActionButton label="읽어 주기" onClick={() => onSpeak(line.text)}>
                  <Volume2 className="h-3.5 w-3.5" />
                </ActionButton>
              )}
            </div>
            {isLast && !busy && line.suggestions && line.suggestions.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {line.suggestions.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => onSuggest(s)}
                    className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-700 hover:border-[color:var(--chat-accent)] hover:text-[color:var(--chat-accent)]"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
