// 공유 챗·위젯·대화로 시험하기가 함께 쓰는 챗 화면.
import {
  ArrowDown,
  ArrowUp,
  Clock,
  Download,
  Headset,
  History,
  MessageSquare,
  Mic,
  MicOff,
  Paperclip,
  SquarePen,
  Square,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { AppIcon } from "@/components/AppIcon";
import { ChatHistory } from "@/components/chat/ChatHistory";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { Markdown } from "@/components/chat/Markdown";
import {
  getRecognition,
  speak,
  sttSupported,
  ttsSupported,
  type SpeechRecognitionLike,
} from "@/components/chat/speech";
import {
  askParentToClose,
  downloadText,
  linesFromSession,
  loadSessions,
  removeSession,
  transcriptMarkdown,
  upsertSession,
  type ChatLine,
  type ChatTransport,
  type SessionEntry,
} from "@/lib/api/chat";
import { errorLines } from "@/lib/api/client";
import type { FeaturesWithHandoff } from "@/lib/api/v5a";
import type { Citation, PublicApp, PublicFeatures, Rating, StoredFile } from "@/lib/api/types";
import { resolveFilePath, type OutputFile } from "@/lib/fileKinds";
import { cn } from "@/lib/cn";
import { isSendKey, sendHint, useEnterToSend } from "@/lib/composer";

export interface ChatViewProps {
  title: string;
  icon?: string;
  /** v0.8 웹앱 로고(올린 그림 주소). 없으면 앱 아이콘 */
  logoUrl?: string | null;
  description?: string;
  features: PublicFeatures;
  inputFields: PublicApp["input_fields"];
  transport: ChatTransport;
  /** 지난 대화를 이 브라우저에 기억할 이름(없으면 기록 기능 끔) */
  historyKey?: string | null;
  /** 위젯(iframe) 안 */
  embed?: boolean;
  /** page: 전체 화면, panel: 빌더 옆 칸 */
  variant?: "page" | "panel";
  accent?: string;
  headerActions?: ReactNode;
  onClose?: () => void;
  /** 바뀔 때마다 새 대화로 */
  resetKey?: number;
  footerNote?: ReactNode;
}

const NEAR_BOTTOM = 80;

export function ChatView({
  title,
  icon,
  logoUrl,
  description,
  features,
  inputFields,
  transport,
  historyKey = null,
  embed = false,
  variant = "page",
  accent = "#4f46e5",
  headerActions,
  onClose,
  resetKey = 0,
  footerNote,
}: ChatViewProps) {
  const enterToSend = useEnterToSend();
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [message, setMessage] = useState("");
  const [extra, setExtra] = useState<Record<string, string>>({});
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [previews, setPreviews] = useState<Record<string, string>>({});
  const [listening, setListening] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [sessions, setSessions] = useState<SessionEntry[]>(() =>
    historyKey ? loadSessions(historyKey) : [],
  );
  const [historyOpen, setHistoryOpen] = useState(false);
  const [wide, setWide] = useState(
    () => typeof window !== "undefined" && window.innerWidth >= 1024,
  );
  const [atBottom, setAtBottom] = useState(true);
  const [loadingSession, setLoadingSession] = useState(false);
  // v0.5: 사람(승인·담당자)을 기다리는 중 / 상담원 연결 중 — 지난 메시지를 주기적으로 다시 읽는다
  const [pending, setPending] = useState(false);
  const [handoff, setHandoff] = useState(false);
  const [handoffBusy, setHandoffBusy] = useState(false);
  const serverCount = useRef(0);

  const sessionRef = useRef<string | undefined>(undefined);
  const abortRef = useRef<AbortController | null>(null);
  const busyRef = useRef(false);
  const atBottomRef = useRef(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const seq = useRef(0);
  const nextId = () => ++seq.current;

  const extraFields = inputFields.filter((f) => f.key !== "message" && f.type !== "file");
  const maxFiles = features.file_upload?.max_files ?? 3;
  const canAttach = Boolean(features.file_upload?.enabled && transport.upload);
  const sttAvailable = Boolean(features.speech?.stt) && sttSupported();
  const ttsAvailable = Boolean(features.speech?.tts) && ttsSupported();
  const showHistory = Boolean(historyKey);
  const sideBySide = showHistory && wide && !embed && variant === "page";

  // 넓은 화면이면 지난 대화를 옆에 펼쳐 둔다
  useEffect(() => {
    const onResize = () => setWide(window.innerWidth >= 1024);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  useEffect(() => {
    if (sideBySide && sessions.length > 0) setHistoryOpen(true);
    // 처음 한 번만
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sideBySide]);

  // 바닥 근처에 있을 때만 새 글을 따라 내려간다(위로 올려 읽는 중이면 그대로)
  useEffect(() => {
    if (!atBottomRef.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines, status]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM;
    atBottomRef.current = near;
    setAtBottom(near);
  };
  const scrollToBottom = () => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo?.({ top: el.scrollHeight, behavior: "smooth" });
    if (!el.scrollTo) el.scrollTop = el.scrollHeight;
    atBottomRef.current = true;
    setAtBottom(true);
  };

  // 입력칸 자동으로 늘리기
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [message]);

  // 위젯 안: Esc로 닫기
  useEffect(() => {
    if (!embed) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") askParentToClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [embed]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      recRef.current?.stop();
    },
    [],
  );

  const patch = (id: number, fn: (l: ChatLine) => ChatLine) =>
    setLines((ls) => ls.map((l) => (l.id === id ? fn(l) : l)));

  const setBusyBoth = (v: boolean) => {
    busyRef.current = v;
    setBusy(v);
  };

  const rememberSession = useCallback(
    (sid: string, firstQuestion: string) => {
      sessionRef.current = sid;
      setSessionId(sid);
      if (historyKey) setSessions(upsertSession(historyKey, sid, firstQuestion));
    },
    [historyKey],
  );

  const send = async (raw: string, opts: { regenerate?: boolean } = {}) => {
    const text = raw.trim();
    if (!text || busyRef.current) return;
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const attached = opts.regenerate ? [] : files;
    const firstQuestion = lines.find((l) => l.role === "user")?.text ?? text;
    if (opts.regenerate) {
      // 마지막 질문 뒤의 답·오류를 지우고 같은 질문을 다시 보낸다
      setLines((ls) => {
        const lastUser = ls.map((l) => l.role).lastIndexOf("user");
        return (lastUser >= 0 ? ls.slice(0, lastUser + 1) : ls).map((x) => ({
          ...x,
          suggestions: undefined,
        }));
      });
    } else {
      setMessage("");
      setFiles([]);
      setLines((ls) => [
        ...ls.map((x) => ({ ...x, suggestions: undefined })),
        {
          id: nextId(),
          role: "user",
          text,
          files: attached,
          createdAt: new Date().toISOString(),
        },
      ]);
    }
    atBottomRef.current = true;
    setBusyBoth(true);

    let streamId: number | null = null;
    let answerId: number | null = null;
    let pending: Partial<ChatLine> = {};
    const ensureStream = () => {
      if (streamId !== null) return streamId;
      const id = nextId();
      streamId = id;
      setLines((ls) => [
        ...ls,
        { id, role: "assistant", text: "", streaming: true, createdAt: new Date().toISOString() },
      ]);
      return id;
    };
    const finishAnswer = (data: Partial<ChatLine>) => {
      const id = streamId ?? nextId();
      const merged = { ...data, ...pending, streaming: false };
      pending = {};
      answerId = id;
      if (streamId !== null) patch(id, (l) => ({ ...l, ...merged }));
      else
        setLines((ls) => [
          ...ls,
          { id, role: "assistant", text: "", createdAt: new Date().toISOString(), ...merged },
        ]);
      streamId = null;
    };
    const attach = (p: Partial<ChatLine>) => {
      if (answerId !== null) {
        const id = answerId;
        patch(id, (l) => ({ ...l, ...p }));
      } else pending = { ...pending, ...p };
    };
    const dropEmptyStream = () => {
      if (streamId === null) return;
      const id = streamId;
      setLines((ls) => ls.filter((l) => !(l.id === id && !l.text)));
      streamId = null;
    };

    try {
      await transport.send(
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
              if (d.session_id) rememberSession(String(d.session_id), firstQuestion);
              break;
            case "status":
              setStatus(String(d.message ?? ""));
              break;
            case "delta": {
              const id = ensureStream();
              const piece = String(d.text ?? "");
              patch(id, (l) => ({ ...l, text: l.text + piece }));
              break;
            }
            case "delta_reset":
              if (streamId !== null) {
                const id = streamId;
                patch(id, (l) => ({ ...l, text: "" }));
              }
              break;
            case "answer":
            case "moderated":
            case "annotated":
              finishAnswer({
                text: String(d.text ?? ""),
                messageId: d.message_id ? String(d.message_id) : undefined,
                outFiles:
                  Array.isArray(d.files) && d.files.length ? (d.files as OutputFile[]) : undefined,
                moderated: ev.event === "moderated",
                annotated: ev.event === "annotated",
              });
              break;
            case "citations":
              if (Array.isArray(ev.data)) attach({ citations: ev.data as Citation[] });
              break;
            case "pending":
              setPending(true);
              break;
            case "handoff":
              dropEmptyStream();
              setHandoff(true);
              if (d.message)
                setLines((ls) => [
                  ...ls,
                  {
                    id: nextId(),
                    role: "assistant",
                    text: String(d.message),
                    serverId: d.message_id ? String(d.message_id) : undefined,
                    createdAt: new Date().toISOString(),
                  },
                ]);
              break;
            case "suggestions":
              if (Array.isArray(ev.data))
                attach({ suggestions: (ev.data as unknown[]).map(String) });
              break;
            case "error":
              dropEmptyStream();
              setLines((ls) => [
                ...ls,
                {
                  id: nextId(),
                  role: "error",
                  text: String(d.message ?? "답을 만들지 못했어요."),
                  hint: (d.hint as string | undefined) ?? "잠시 후 다시 시도해 주세요.",
                },
              ]);
              break;
            case "done":
              if (d.session_id && !sessionRef.current)
                rememberSession(String(d.session_id), firstQuestion);
              break;
          }
        },
        ctrl.signal,
      );
    } catch (err) {
      if (ctrl.signal.aborted) {
        if (streamId !== null) {
          const id = streamId;
          patch(id, (l) => ({ ...l, streaming: false, stopped: true }));
          setLines((ls) => ls.filter((l) => !(l.id === id && !l.text && !l.stopped)));
        }
      } else {
        dropEmptyStream();
        const { message: m, hint } = errorLines(err);
        setLines((ls) => [...ls, { id: nextId(), role: "error", text: m, hint }]);
      }
    } finally {
      // 조각만 오고 최종 답이 오지 않은 채 끝났으면 멈춘 것으로 둔다
      if (streamId !== null) {
        const id = streamId;
        patch(id, (l) => ({ ...l, streaming: false, stopped: l.stopped ?? true }));
      }
      abortRef.current = null;
      setBusyBoth(false);
      setStatus("");
    }
  };

  const stop = () => abortRef.current?.abort();

  const lastUserText = () => [...lines].reverse().find((l) => l.role === "user")?.text ?? "";
  const regenerate = () => void send(lastUserText(), { regenerate: true });

  const newChat = () => {
    abortRef.current?.abort();
    sessionRef.current = undefined;
    setSessionId(undefined);
    setLines([]);
    setMessage("");
    setFiles([]);
    setStatus("");
    setPending(false);
    setHandoff(false);
    serverCount.current = 0;
    if (!sideBySide) setHistoryOpen(false);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  };

  // 바깥(빌더 '새로 시작')에서 새 대화를 요청
  const firstReset = useRef(true);
  useEffect(() => {
    if (firstReset.current) {
      firstReset.current = false;
      return;
    }
    newChat();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  const openSession = async (sid: string) => {
    if (!transport.loadSession || sid === sessionId) {
      if (!sideBySide) setHistoryOpen(false);
      return;
    }
    abortRef.current?.abort();
    setLoadingSession(true);
    if (!sideBySide) setHistoryOpen(false);
    try {
      const msgs = await transport.loadSession(sid);
      sessionRef.current = sid;
      setSessionId(sid);
      atBottomRef.current = true;
      setLines(linesFromSession(msgs, nextId));
      serverCount.current = msgs.length;
      if (transport.sessionState) {
        const st = await transport.sessionState(sid).catch(() => null);
        setHandoff(st?.status === "handoff");
        setPending(Boolean(st?.waiting));
      }
    } catch (err) {
      const { message: m, hint } = errorLines(err);
      if (historyKey) setSessions(removeSession(historyKey, sid));
      setLines([{ id: nextId(), role: "error", text: m, hint }]);
    } finally {
      setLoadingSession(false);
    }
  };

  // 늦게 온 결과·상담원 답: 기다리는 동안 8초마다 지난 메시지를 다시 읽는다
  useEffect(() => {
    if (!(pending || handoff) || !sessionId || !transport.loadSession) return;
    const load = transport.loadSession;
    const sid = sessionId;
    let stopped = false;
    const tick = async () => {
      if (busyRef.current || stopped) return;
      try {
        const msgs = await load(sid);
        if (stopped || busyRef.current || sessionRef.current !== sid) return;
        if (msgs.length !== serverCount.current) {
          serverCount.current = msgs.length;
          setLines(linesFromSession(msgs, nextId));
        }
        if (transport.sessionState) {
          const st = await transport.sessionState(sid);
          if (stopped) return;
          setHandoff(st.status === "handoff");
          setPending(st.waiting);
        }
      } catch {
        // 잠깐 끊겨도 다음 번에 다시 본다
      }
    };
    const t = window.setInterval(() => void tick(), 8000);
    return () => {
      stopped = true;
      window.clearInterval(t);
    };
  }, [pending, handoff, sessionId, transport]);

  // 이미지·파일 단계가 만든 파일: 공유 링크면 서명 링크, 앱 안 시험이면 실행 기록 경로
  const resolveFile = (f: OutputFile, inline: boolean) =>
    resolveFilePath(f, { token: transport.fileToken }, inline);

  const handoffEnabled = Boolean((features as FeaturesWithHandoff).handoff?.enabled);
  const askHuman = async () => {
    if (!sessionId || !transport.requestHandoff || handoff) return;
    setHandoffBusy(true);
    try {
      const res = (await transport.requestHandoff(sessionId)) as {
        message?: { id: string; content: string } | null;
      };
      setHandoff(true);
      if (res?.message)
        setLines((ls) => [
          ...ls,
          {
            id: nextId(),
            role: "assistant",
            text: res.message?.content ?? "",
            serverId: res.message?.id,
            createdAt: new Date().toISOString(),
          },
        ]);
    } catch (err) {
      const { message: m, hint } = errorLines(err);
      setLines((ls) => [...ls, { id: nextId(), role: "error", text: m, hint }]);
    } finally {
      setHandoffBusy(false);
    }
  };

  const forget = (sid: string) => {
    if (!historyKey) return;
    setSessions(removeSession(historyKey, sid));
    if (sid === sessionId) newChat();
  };

  const rate = async (line: ChatLine, rating: Rating) => {
    if (!line.messageId || !transport.feedback) return;
    const next = line.rating === rating ? null : rating;
    patch(line.id, (l) => ({ ...l, rating: next }));
    try {
      await transport.feedback(line.messageId, next);
    } catch {
      patch(line.id, (l) => ({ ...l, rating: line.rating }));
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

  const attachFiles = async (list: FileList | null) => {
    if (!list?.length || !transport.upload) return;
    const room = Math.max(0, maxFiles - files.length);
    const picked = Array.from(list).slice(0, room);
    setUploading(true);
    try {
      const uploaded: StoredFile[] = [];
      const thumbs: Record<string, string> = {};
      for (const f of picked) {
        const stored = await transport.upload(f);
        uploaded.push(stored);
        // 사진은 보내기 전에 작은 미리 보기를 보여 준다(v0.6 비전, 브라우저 안에서만)
        if (f.type.startsWith("image/") && typeof URL.createObjectURL === "function") {
          thumbs[stored.id] = URL.createObjectURL(f);
        }
      }
      setPreviews((p) => ({ ...p, ...thumbs }));
      setFiles((fs) => [...fs, ...uploaded]);
    } catch (err) {
      const { message: m, hint } = errorLines(err);
      setLines((ls) => [...ls, { id: nextId(), role: "error", text: m, hint }]);
    } finally {
      setUploading(false);
    }
  };

  const exportChat = () => {
    const stamp = new Date().toISOString().slice(0, 10);
    downloadText(`${title}-대화-${stamp}.md`, transcriptMarkdown(title, lines));
  };

  const lastIdx = lines.length - 1;
  const streaming = lines.some((l) => l.streaming);
  const panel = variant === "panel";
  const narrow = embed || panel;
  const iconBtn =
    "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-800 disabled:opacity-40 disabled:hover:bg-transparent";

  return (
    <div
      className="relative flex h-full min-h-0 flex-col bg-slate-50"
      style={{ "--chat-accent": accent } as CSSProperties}
    >
      <header className="flex shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-2.5 py-2 sm:px-3">
        {showHistory && (
          <button
            type="button"
            className={iconBtn}
            aria-label={historyOpen ? "지난 대화 닫기" : "지난 대화 보기"}
            aria-expanded={historyOpen}
            title="지난 대화"
            onClick={() => setHistoryOpen((v) => !v)}
          >
            <History className="h-[18px] w-[18px]" />
          </button>
        )}
        <AppIcon name={title} icon={icon} size="sm" logoUrl={logoUrl} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-slate-900">{title}</p>
          {!narrow && description && (
            <p className="truncate text-xs text-slate-500">{description}</p>
          )}
        </div>
        <button
          type="button"
          className={iconBtn}
          aria-label="새 대화"
          title="새 대화"
          onClick={newChat}
          disabled={lines.length === 0 && !busy}
        >
          <SquarePen className="h-[18px] w-[18px]" />
        </button>
        <button
          type="button"
          className={iconBtn}
          aria-label="대화 내보내기"
          title="대화 내보내기(.md)"
          onClick={exportChat}
          disabled={lines.length === 0 || busy}
        >
          <Download className="h-[18px] w-[18px]" />
        </button>
        {handoffEnabled && transport.requestHandoff && (
          <button
            type="button"
            onClick={() => void askHuman()}
            disabled={!sessionId || handoff || handoffBusy || busy}
            title={
              handoff
                ? "상담원과 연결되어 있어요"
                : sessionId
                  ? "사람 상담원에게 대화를 넘겨요"
                  : "먼저 한마디 남긴 뒤 연결할 수 있어요"
            }
            className="inline-flex h-8 shrink-0 items-center gap-1 rounded-lg border border-slate-200 px-2 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:opacity-50"
          >
            <Headset className="h-3.5 w-3.5" />
            <span className={cn(narrow && "sr-only")}>
              {handoff ? "상담원 연결 중" : "상담원 연결"}
            </span>
          </button>
        )}
        {headerActions}
        {onClose && (
          <button
            type="button"
            className={iconBtn}
            aria-label="닫기"
            title="닫기"
            onClick={onClose}
          >
            <X className="h-[18px] w-[18px]" />
          </button>
        )}
      </header>

      <div className="relative flex min-h-0 flex-1">
        {showHistory && historyOpen && (
          <ChatHistory
            sessions={sessions}
            activeId={sessionId}
            overlay={!sideBySide}
            onSelect={(id) => void openSession(id)}
            onNew={newChat}
            onRemove={forget}
            onClose={() => setHistoryOpen(false)}
          />
        )}
        <div className="relative flex min-w-0 flex-1 flex-col">
          <div className="relative min-h-0 flex-1">
            <div
              ref={scrollRef}
              onScroll={onScroll}
              className="absolute inset-0 overflow-y-auto"
              role="log"
              aria-live="polite"
              aria-busy={busy}
            >
              <div
                className={cn("space-y-4 px-3 py-4 sm:px-4", !narrow && "mx-auto w-full max-w-3xl")}
              >
                {loadingSession && (
                  <p className="py-8 text-center text-sm text-slate-400">
                    지난 대화를 불러오는 중…
                  </p>
                )}
                {!loadingSession && lines.length === 0 && (
                  <div
                    className={cn(
                      "flex flex-col items-center text-center",
                      narrow ? "pt-6" : "pt-12",
                    )}
                  >
                    <AppIcon name={title} icon={icon} size="lg" logoUrl={logoUrl} />
                    <p className="mt-3 text-lg font-bold text-slate-900">{title}</p>
                    <div className="mt-1.5 max-w-md text-sm text-slate-600">
                      {features.opening_statement ? (
                        <Markdown text={features.opening_statement} />
                      ) : (
                        <p>무엇이든 물어보세요.</p>
                      )}
                    </div>
                    {(features.suggested_questions ?? []).length > 0 && (
                      <div
                        className={cn(
                          "mt-5 grid w-full max-w-xl gap-2 text-left",
                          !narrow && "sm:grid-cols-2",
                        )}
                      >
                        {(features.suggested_questions ?? []).map((q) => (
                          <button
                            key={q}
                            type="button"
                            onClick={() => void send(q)}
                            className="group flex items-start gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-3 text-sm text-slate-700 shadow-sm transition hover:-translate-y-0.5 hover:border-[color:var(--chat-accent)] hover:shadow-md"
                          >
                            <MessageSquare className="mt-0.5 h-4 w-4 shrink-0 text-slate-400 group-hover:text-[color:var(--chat-accent)]" />
                            <span>{q}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {lines.map((l, i) => (
                  <ChatMessage
                    key={l.id}
                    line={l}
                    appName={title}
                    appIcon={icon}
                    isLast={i === lastIdx}
                    busy={busy}
                    canRate={Boolean(transport.feedback)}
                    canSpeak={ttsAvailable}
                    onRate={(line, r) => void rate(line, r)}
                    onRegenerate={regenerate}
                    onRetry={regenerate}
                    onSuggest={(q) => void send(q)}
                    onSpeak={speak}
                    resolveFile={resolveFile}
                  />
                ))}
                {busy &&
                  !streaming &&
                  !lines.some((l, i) => i === lastIdx && l.role === "assistant") && (
                    <p className="flex items-center gap-1 pl-1 text-xs text-slate-400 sm:pl-9">
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:120ms]" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:240ms]" />
                      <span className="ml-1">{status || "생각하는 중…"}</span>
                    </p>
                  )}
              </div>
            </div>

            {!atBottom && lines.length > 0 && (
              <button
                type="button"
                onClick={scrollToBottom}
                aria-label="맨 아래로"
                className="absolute bottom-3 left-1/2 z-10 inline-flex h-9 w-9 -translate-x-1/2 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-600 shadow-lift hover:text-slate-900"
              >
                <ArrowDown className="h-4 w-4" />
              </button>
            )}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (busy) stop();
              else void send(message);
            }}
            className="shrink-0 border-t border-slate-200 bg-white p-2.5 pb-[max(0.625rem,env(safe-area-inset-bottom))] sm:p-3"
          >
            <div className={cn("space-y-2", !narrow && "mx-auto max-w-3xl")}>
              {(handoff || pending) && (
                <p
                  role="status"
                  className="flex items-center gap-1.5 rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs text-amber-800"
                >
                  {handoff ? (
                    <>
                      <Headset className="h-3.5 w-3.5 shrink-0" />
                      상담원과 연결 중이에요. 적어 주신 말은 상담원에게 전달되고, 답이 오면 여기에
                      보여요.
                    </>
                  ) : (
                    <>
                      <Clock className="h-3.5 w-3.5 shrink-0" />
                      담당자 처리를 기다리고 있어요. 결과가 나오면 이 대화에 보여 드려요.
                    </>
                  )}
                </p>
              )}
              {extraFields.length > 0 && (
                <div className="grid gap-1.5 sm:grid-cols-2">
                  {extraFields.map((f) => (
                    // 값을 넣어도 무슨 칸인지 보이게 이름을 칸 왼쪽에 둔다
                    <label
                      key={f.key}
                      className="flex min-w-0 items-center gap-2 rounded-lg border border-slate-200 bg-white pl-2.5 focus-within:border-indigo-400"
                    >
                      <span className="shrink-0 text-xs font-medium text-slate-500">
                        {f.label || f.key}
                        {f.required && <span className="text-red-500">*</span>}
                      </span>
                      <input
                        aria-label={f.label || f.key}
                        type={f.type === "number" ? "number" : "text"}
                        value={extra[f.key] ?? ""}
                        onChange={(e) => setExtra({ ...extra, [f.key]: e.target.value })}
                        className="h-9 min-w-0 flex-1 rounded-r-lg bg-transparent px-2 text-sm text-slate-900 focus:outline-none"
                      />
                    </label>
                  ))}
                </div>
              )}
              {files.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {files.map((f) => (
                    <span
                      key={f.id}
                      className="inline-flex max-w-full items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600"
                    >
                      {previews[f.id] ? (
                        <img
                          src={previews[f.id]}
                          alt=""
                          className="h-6 w-6 shrink-0 rounded object-cover"
                        />
                      ) : (
                        <Paperclip className="h-3 w-3 shrink-0" />
                      )}
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
              <div className="flex items-end gap-1 rounded-2xl border border-slate-200 bg-white p-1.5 pl-2 transition focus-within:border-[color:var(--chat-accent)] focus-within:shadow-[0_0_0_4px_rgb(99_102_241/0.1)]">
                {canAttach && (
                  <>
                    <input
                      ref={fileRef}
                      type="file"
                      multiple
                      className="hidden"
                      aria-label="첨부 파일"
                      onChange={(e) => {
                        void attachFiles(e.target.files);
                        e.target.value = "";
                      }}
                    />
                    <button
                      type="button"
                      aria-label="파일 첨부"
                      title={`파일·사진 첨부(최대 ${maxFiles}개)`}
                      disabled={uploading || files.length >= maxFiles}
                      onClick={() => fileRef.current?.click()}
                      className={cn(iconBtn, "h-9 w-9 rounded-xl")}
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
                    className={cn(iconBtn, "h-9 w-9 rounded-xl", listening && "text-red-600")}
                  >
                    {listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                  </button>
                )}
                <textarea
                  ref={inputRef}
                  aria-label="메시지"
                  rows={1}
                  placeholder={listening ? "듣고 있어요…" : `${title}에게 물어보세요`}
                  className="max-h-40 min-h-[36px] flex-1 resize-none border-0 bg-transparent py-2 text-[15px] text-slate-900 placeholder:text-slate-400 focus:outline-none sm:text-sm"
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
                {busy ? (
                  <button
                    type="submit"
                    aria-label="멈추기"
                    title="답 멈추기"
                    className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white hover:bg-indigo-500"
                  >
                    <Square className="h-3.5 w-3.5 fill-current" />
                  </button>
                ) : (
                  <button
                    type="submit"
                    aria-label="보내기"
                    disabled={!message.trim()}
                    className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[color:var(--chat-accent)] text-white transition hover:opacity-90 disabled:bg-slate-200 disabled:text-slate-400"
                  >
                    <ArrowUp className="h-4 w-4" />
                  </button>
                )}
              </div>
              {!narrow && (
                <p className="text-center text-[11px] text-slate-400">
                  {footerNote ?? "AI 답은 틀릴 수 있어요. 중요한 내용은 한 번 더 확인하세요."}
                </p>
              )}
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
