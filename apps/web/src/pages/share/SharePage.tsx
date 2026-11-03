import {
  ArrowUp,
  BookMarked,
  ChevronDown,
  Mic,
  MicOff,
  Paperclip,
  ShieldBan,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Volume2,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useLoggedIn } from "@/app/useAuthState";
import { AppIcon } from "@/components/AppIcon";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Input } from "@/components/ui/input";
import { HelpButton } from "@/help/HelpButton";
import { ko } from "@/i18n/ko";
import { errorLines } from "@/lib/api/client";
import { isSendKey, sendHint, useEnterToSend } from "@/lib/composer";
import { sendPublicChat, usePublicApp } from "@/lib/api/resources";
import type { Citation, PublicAppV2, Rating, StoredFile } from "@/lib/api/types";
import { sendPublicFeedback, uploadPublicFile } from "@/lib/api/v2";
import { cn } from "@/lib/cn";

interface ChatLine {
  id: number;
  role: "user" | "assistant" | "error";
  text: string;
  hint?: string;
  messageId?: string;
  citations?: Citation[];
  suggestions?: string[];
  moderated?: boolean;
  annotated?: boolean;
  rating?: Rating | null;
  files?: StoredFile[];
}

interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
}

function getRecognition(): SpeechRecognitionLike | null {
  const w = window as unknown as Record<string, unknown>;
  const Ctor = (w.SpeechRecognition ?? w.webkitSpeechRecognition) as
    (new () => SpeechRecognitionLike) | undefined;
  return Ctor ? new Ctor() : null;
}

function speak(text: string) {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "ko-KR";
  window.speechSynthesis.speak(u);
}

function Citations({ items }: { items: Citation[] }) {
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
            className={cn(
              "inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]",
              open === c.index
                ? "border-indigo-300 bg-indigo-50 text-indigo-700"
                : "border-slate-200 bg-white text-slate-600 hover:border-slate-300",
            )}
          >
            <span className="font-semibold">{c.index}</span>
            <span className="truncate">{c.filename}</span>
            <ChevronDown className={cn("h-3 w-3 shrink-0", open === c.index && "rotate-180")} />
          </button>
        ))}
      </div>
      {items
        .filter((c) => c.index === open)
        .map((c) => (
          <p
            key={c.index}
            className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600"
          >
            {c.content}
          </p>
        ))}
    </div>
  );
}

/** 배포된 앱을 쓰는 화면. 위젯(iframe)은 ?embed=1 로 연다. */
export default function SharePage() {
  const { token = "" } = useParams();
  const [params] = useSearchParams();
  const embed = params.get("embed") === "1";
  const loggedIn = useLoggedIn();
  const enterToSend = useEnterToSend();
  const app = usePublicApp(token);
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [message, setMessage] = useState("");
  const [extra, setExtra] = useState<Record<string, string>>({});
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [listening, setListening] = useState(false);
  const sessionRef = useRef<string | undefined>(undefined);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ block: "end" });
  }, [lines, status]);

  useEffect(() => () => recRef.current?.stop(), []);

  if (app.isLoading) return <Loading />;
  if (app.error)
    return (
      <div className="mx-auto max-w-md p-6">
        <ErrorBox error={app.error} />
      </div>
    );
  const info = app.data as PublicAppV2 | undefined;
  if (!info) return null;
  const features = info.features ?? {};
  const extraFields = info.input_fields.filter((f) => f.key !== "message" && f.type !== "file");
  const maxFiles = features.file_upload?.max_files ?? 3;
  const sttAvailable =
    Boolean(features.speech?.stt) &&
    typeof window !== "undefined" &&
    Boolean(
      (window as unknown as Record<string, unknown>).SpeechRecognition ??
      (window as unknown as Record<string, unknown>).webkitSpeechRecognition,
    );
  const ttsAvailable =
    Boolean(features.speech?.tts) && typeof window !== "undefined" && "speechSynthesis" in window;

  const nextId = () => ++seq.current;

  const patchLast = (fn: (l: ChatLine) => ChatLine) =>
    setLines((ls) => {
      const idx = [...ls].reverse().findIndex((l) => l.role === "assistant");
      if (idx < 0) return ls;
      const real = ls.length - 1 - idx;
      return ls.map((l, i) => (i === real ? fn(l) : l));
    });

  const send = async (raw: string) => {
    const text = raw.trim();
    if (!text || busy) return;
    const attached = files;
    setMessage("");
    setFiles([]);
    setBusy(true);
    // 앞선 답의 '이어서 물어볼 질문'은 새 질문을 보내면 지운다
    setLines((l) => [
      ...l.map((x) => ({ ...x, suggestions: undefined })),
      { id: nextId(), role: "user", text, files: attached },
    ]);
    // 출처·이어질 질문이 답보다 먼저 와도 이번 답에 붙도록 모아 둔다
    let answered = false;
    let pending: Partial<ChatLine> = {};
    const addAnswer = (line: Omit<ChatLine, "id">) => {
      answered = true;
      const merged = { ...line, ...pending };
      pending = {};
      setLines((l) => [...l, { id: nextId(), ...merged }]);
    };
    const attachToAnswer = (patch: Partial<ChatLine>) => {
      if (answered) patchLast((x) => ({ ...x, ...patch }));
      else pending = { ...pending, ...patch };
    };
    try {
      await sendPublicChat(
        token,
        {
          message: text,
          session_id: sessionRef.current,
          input: extraFields.length ? { ...extra, message: text } : undefined,
          files: attached.length ? attached.map((f) => f.id) : undefined,
        },
        (ev) => {
          const d = (ev.data ?? {}) as Record<string, unknown>;
          switch (ev.event) {
            case "session":
              sessionRef.current = String(d.session_id);
              break;
            case "status":
              setStatus(String(d.message ?? ""));
              break;
            case "answer":
              addAnswer({
                role: "assistant",
                text: String(d.text ?? ""),
                messageId: d.message_id ? String(d.message_id) : undefined,
              });
              break;
            case "moderated":
            case "annotated":
              addAnswer({
                role: "assistant",
                text: String(d.text ?? ""),
                messageId: d.message_id ? String(d.message_id) : undefined,
                moderated: ev.event === "moderated",
                annotated: ev.event === "annotated",
              });
              break;
            case "citations":
              if (Array.isArray(ev.data)) attachToAnswer({ citations: ev.data as Citation[] });
              break;
            case "suggestions":
              if (Array.isArray(ev.data))
                attachToAnswer({ suggestions: (ev.data as unknown[]).map(String) });
              break;
            case "error":
              setLines((l) => [
                ...l,
                {
                  id: nextId(),
                  role: "error",
                  text: String(d.message ?? "문제가 생겼어요."),
                  hint: d.hint as string | undefined,
                },
              ]);
              break;
            case "done":
              if (d.session_id) sessionRef.current = String(d.session_id);
              break;
          }
        },
      );
    } catch (err) {
      const { message: m, hint } = errorLines(err);
      setLines((l) => [...l, { id: nextId(), role: "error", text: m, hint }]);
    } finally {
      setBusy(false);
      setStatus("");
    }
  };

  const rate = async (line: ChatLine, rating: Rating) => {
    if (!line.messageId) return;
    const next = line.rating === rating ? null : rating;
    setLines((ls) => ls.map((l) => (l.id === line.id ? { ...l, rating: next } : l)));
    try {
      await sendPublicFeedback(token, line.messageId, next);
    } catch {
      setLines((ls) => ls.map((l) => (l.id === line.id ? { ...l, rating: line.rating } : l)));
    }
  };

  const toggleMic = () => {
    if (listening) {
      recRef.current?.stop();
      return;
    }
    const rec = getRecognition();
    if (!rec) return;
    rec.lang = "ko-KR";
    rec.interimResults = false;
    rec.continuous = false;
    rec.onresult = (e) => {
      const t = Array.from(e.results)
        .map((r) => r[0]?.transcript ?? "")
        .join(" ");
      setMessage((m) => (m ? `${m} ${t}` : t));
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  };

  const attach = async (list: FileList | null) => {
    if (!list?.length) return;
    const room = Math.max(0, maxFiles - files.length);
    const picked = Array.from(list).slice(0, room);
    setUploading(true);
    try {
      const uploaded: StoredFile[] = [];
      for (const f of picked) uploaded.push(await uploadPublicFile(token, f));
      setFiles((fs) => [...fs, ...uploaded]);
    } catch (err) {
      const { message: m, hint } = errorLines(err);
      setLines((l) => [...l, { id: nextId(), role: "error", text: m, hint }]);
    } finally {
      setUploading(false);
    }
  };

  const blocked = !info.can_use;
  const lastAssistant = [...lines].reverse().find((l) => l.role === "assistant");

  return (
    <div className="flex h-[100dvh] flex-col bg-slate-50">
      <header className="flex shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-3 py-2.5 sm:px-4">
        <AppIcon name={info.name} icon={info.icon} size="sm" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{info.name}</p>
          {!embed && info.description && (
            <p className="truncate text-xs text-slate-500">{info.description}</p>
          )}
        </div>
        {!embed && (
          <span className="hidden text-xs text-slate-400 sm:inline">{ko.appName}로 만들었어요</span>
        )}
        <HelpButton page="share" fullLink={false} />
      </header>
      {blocked ? (
        <div className="mx-auto w-full max-w-md p-6 text-sm">
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
            <p className="font-medium text-amber-900">
              {info.requires_login && !loggedIn
                ? "로그인이 필요한 앱이에요."
                : "이 앱을 쓸 권한이 없어요."}
            </p>
            <p className="text-amber-800">
              {info.requires_login && !loggedIn
                ? "워크스페이스 계정으로 로그인한 뒤 다시 열어 주세요."
                : "앱을 배포한 사람에게 사용 권한을 요청하세요."}
            </p>
          </div>
          {info.requires_login && !loggedIn && (
            <Link
              to={`/login?next=${encodeURIComponent(`/share/${token}${embed ? "?embed=1" : ""}`)}`}
              target={embed ? "_blank" : undefined}
              className="mt-3 inline-block text-indigo-600"
            >
              로그인하러 가기
            </Link>
          )}
        </div>
      ) : (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div
              className={cn("space-y-4 px-3 py-4 sm:px-4", !embed && "mx-auto w-full max-w-2xl")}
            >
              {lines.length === 0 && (
                <div className="space-y-3 pt-6 text-center">
                  <span className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white">
                    <Sparkles className="h-5 w-5" />
                  </span>
                  <p className="whitespace-pre-wrap text-sm text-slate-600">
                    {features.opening_statement || "무엇이든 물어보세요."}
                  </p>
                  {(features.suggested_questions ?? []).length > 0 && (
                    <div className="flex flex-wrap justify-center gap-2">
                      {(features.suggested_questions ?? []).map((q) => (
                        <button
                          key={q}
                          type="button"
                          onClick={() => void send(q)}
                          className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-[13px] text-slate-600 hover:border-indigo-300 hover:text-indigo-700"
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {lines.map((l) => (
                <div
                  key={l.id}
                  className={cn("flex", l.role === "user" ? "justify-end" : "justify-start")}
                >
                  <div
                    className={cn(
                      "max-w-[88%] sm:max-w-[80%]",
                      l.role === "assistant" && "w-full sm:w-auto",
                    )}
                  >
                    <div
                      className={cn(
                        "whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm leading-relaxed",
                        l.role === "user" && "rounded-br-md bg-indigo-600 text-white",
                        l.role === "assistant" &&
                          "rounded-bl-md border border-slate-200 bg-white text-slate-900",
                        l.role === "error" && "border border-red-200 bg-red-50 text-red-900",
                      )}
                    >
                      {l.text}
                      {l.hint && <p className="mt-0.5 text-xs text-red-700">{l.hint}</p>}
                      {l.files && l.files.length > 0 && (
                        <p className="mt-1 text-xs opacity-80">
                          📎 {l.files.map((f) => f.filename).join(", ")}
                        </p>
                      )}
                    </div>
                    {l.role === "assistant" && (
                      <>
                        {l.citations && l.citations.length > 0 && <Citations items={l.citations} />}
                        <div className="mt-1 flex items-center gap-1 text-slate-400">
                          {l.moderated && (
                            <span className="inline-flex items-center gap-0.5 text-[11px]">
                              <ShieldBan className="h-3 w-3" /> 정해진 답
                            </span>
                          )}
                          {l.annotated && <span className="text-[11px]">· 등록된 답</span>}
                          {l.messageId && (
                            <>
                              <button
                                type="button"
                                aria-label="좋아요"
                                aria-pressed={l.rating === "like"}
                                onClick={() => void rate(l, "like")}
                                className={cn(
                                  "rounded-md p-1 hover:bg-slate-100",
                                  l.rating === "like" && "text-emerald-600",
                                )}
                              >
                                <ThumbsUp className="h-3.5 w-3.5" />
                              </button>
                              <button
                                type="button"
                                aria-label="싫어요"
                                aria-pressed={l.rating === "dislike"}
                                onClick={() => void rate(l, "dislike")}
                                className={cn(
                                  "rounded-md p-1 hover:bg-slate-100",
                                  l.rating === "dislike" && "text-red-600",
                                )}
                              >
                                <ThumbsDown className="h-3.5 w-3.5" />
                              </button>
                            </>
                          )}
                          {ttsAvailable && (
                            <button
                              type="button"
                              aria-label="읽어 주기"
                              onClick={() => speak(l.text)}
                              className="rounded-md p-1 hover:bg-slate-100"
                            >
                              <Volume2 className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </div>
                        {l === lastAssistant &&
                          l.suggestions &&
                          l.suggestions.length > 0 &&
                          !busy && (
                            <div className="mt-1.5 flex flex-wrap gap-1.5">
                              {l.suggestions.map((s) => (
                                <button
                                  key={s}
                                  type="button"
                                  onClick={() => void send(s)}
                                  className="rounded-full border border-indigo-200 bg-indigo-50/60 px-3 py-1 text-xs text-indigo-700 hover:bg-indigo-100"
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
              ))}
              {(status || busy) && (
                <p className="flex items-center gap-1 text-xs text-slate-400">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:120ms]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:240ms]" />
                  <span className="ml-1">{status}</span>
                </p>
              )}
              <div ref={bottomRef} />
            </div>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void send(message);
            }}
            className="shrink-0 border-t border-slate-200 bg-white p-2.5 pb-[max(0.625rem,env(safe-area-inset-bottom))] sm:p-3"
          >
            <div className={cn("space-y-2", !embed && "mx-auto max-w-2xl")}>
              {extraFields.map((f) => (
                <Input
                  key={f.key}
                  aria-label={f.label || f.key}
                  placeholder={f.label || f.key}
                  value={extra[f.key] ?? ""}
                  onChange={(e) => setExtra({ ...extra, [f.key]: e.target.value })}
                />
              ))}
              {files.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {files.map((f) => (
                    <span
                      key={f.id}
                      className="inline-flex max-w-full items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600"
                    >
                      <Paperclip className="h-3 w-3 shrink-0" />
                      <span className="truncate">{f.filename}</span>
                      <button
                        type="button"
                        aria-label={`${f.filename} 빼기`}
                        onClick={() => setFiles(files.filter((x) => x.id !== f.id))}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <div className="flex items-end gap-1.5 rounded-2xl border border-slate-200 bg-white p-1.5 pl-2 focus-within:border-indigo-400 focus-within:ring-4 focus-within:ring-indigo-500/10">
                {features.file_upload?.enabled && (
                  <>
                    <input
                      ref={fileRef}
                      type="file"
                      multiple
                      className="hidden"
                      aria-label="첨부 파일"
                      onChange={(e) => {
                        void attach(e.target.files);
                        e.target.value = "";
                      }}
                    />
                    <button
                      type="button"
                      aria-label="파일 첨부"
                      disabled={uploading || files.length >= maxFiles}
                      onClick={() => fileRef.current?.click()}
                      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-slate-500 hover:bg-slate-100 disabled:opacity-40"
                    >
                      <Paperclip className={cn("h-4 w-4", uploading && "animate-pulse")} />
                    </button>
                  </>
                )}
                {sttAvailable && (
                  <button
                    type="button"
                    aria-label={listening ? "듣기 멈추기" : "말로 묻기"}
                    onClick={toggleMic}
                    className={cn(
                      "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl hover:bg-slate-100",
                      listening ? "text-red-600" : "text-slate-500",
                    )}
                  >
                    {listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                  </button>
                )}
                <textarea
                  aria-label="메시지"
                  rows={1}
                  placeholder={listening ? "듣고 있어요…" : "메시지를 입력하세요"}
                  className="max-h-32 min-h-[36px] flex-1 resize-none border-0 bg-transparent py-2 text-[15px] placeholder:text-slate-400 focus:outline-none sm:text-sm"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  title={sendHint(enterToSend)}
                  onKeyDown={(e) => {
                    if (isSendKey(e, enterToSend)) {
                      e.preventDefault();
                      void send(message);
                    }
                  }}
                />
                <button
                  type="submit"
                  aria-label="보내기"
                  disabled={busy || !message.trim()}
                  className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-slate-200 disabled:text-slate-400"
                >
                  <ArrowUp className="h-4 w-4" />
                </button>
              </div>
            </div>
          </form>
        </>
      )}
    </div>
  );
}
