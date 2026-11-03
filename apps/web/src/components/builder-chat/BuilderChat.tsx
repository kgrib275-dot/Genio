import { useQueryClient } from "@tanstack/react-query";
import { ArrowUp, RotateCcw, Sparkles } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  AskUserCard,
  MarketSuggestionCard,
  TestResultCard,
  ToolCallGroup,
} from "@/components/builder-chat/cards";
import { emptyDraft, reduceDraft, type DraftTurn } from "@/components/builder-chat/turn";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { toast } from "@/components/ui/toast-store";
import {
  createBuilderSession,
  sendBuilderMessage,
  useBuilderMessages,
  useBuilderSession,
  type BuilderSendBody,
} from "@/lib/api/builder";
import { errorLines } from "@/lib/api/client";
import { useInstallMarketItem } from "@/lib/api/resources";
import {
  normalizeGraph,
  type BuilderMessage,
  type Graph,
  type PatchOp,
  type TurnRecord,
} from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { isSendKey, sendHint, useEnterToSend } from "@/lib/composer";
import { touchedNodeIds, useCanvas } from "@/store/canvas";
import { takePendingPrompt } from "@/store/pendingPrompt";
import { canManage, useSession } from "@/store/session";

const EXAMPLES = [
  "고객 문의 메일을 분류해서 담당자 슬랙으로 보내 줘",
  "사내 규정 문서로 질문에 답하는 챗봇을 만들어 줘",
  "주간 보고 초안을 만들어서 승인 후 메일로 보내 줘",
];

function TurnBody({
  content,
  record,
  active,
  busy,
  onPick,
  onInstall,
  installing,
}: {
  content: string;
  record: TurnRecord | DraftTurn | null;
  active: boolean;
  busy: boolean;
  onPick: (o: string) => void;
  onInstall: (key: string) => void;
  installing: boolean;
}) {
  const role = useSession((s) => s.role);
  return (
    <div className="space-y-2">
      {content && (
        <p className="whitespace-pre-wrap text-[14px] leading-relaxed text-slate-800">{content}</p>
      )}
      {(record?.tool_calls ?? []).length > 0 && (
        <ToolCallGroup calls={record?.tool_calls ?? []} busy={active && busy} />
      )}
      {record?.test_result && <TestResultCard result={record.test_result} />}
      {record?.market_suggestion && (
        <MarketSuggestionCard
          suggestion={record.market_suggestion}
          active={active && !busy}
          canInstall={canManage(role)}
          installing={installing}
          onInstall={() => onInstall(record.market_suggestion?.item.key ?? "")}
        />
      )}
      {record?.ask_user && (
        <AskUserCard ask={record.ask_user} active={active && !busy} onPick={onPick} />
      )}
    </div>
  );
}

export interface BuilderChatViewProps {
  sessionId: string;
  appId?: string;
  history: BuilderMessage[];
  wsId: string;
  onNewSession?: () => void;
}

/** 빌더 챗 본체. 세션과 이전 메시지를 받아서 대화를 이어 간다. */
export function BuilderChatView({
  sessionId,
  appId,
  history,
  wsId,
  onNewSession,
}: BuilderChatViewProps) {
  const [messages, setMessages] = useState<BuilderMessage[]>(history);
  const [draft, setDraft] = useState<DraftTurn | null>(null);
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState("");
  const enterToSend = useEnterToSend();
  const [streamError, setStreamError] = useState<unknown>(null);
  const install = useInstallMarketItem(wsId);
  const qc = useQueryClient();
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => setMessages(history), [history]);
  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages, draft]);

  const send = async (body: BuilderSendBody) => {
    if (busy || !body.content.trim()) return;
    setBusy(true);
    setStreamError(null);
    setDraft(emptyDraft());
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let finished = false;
    try {
      await sendBuilderMessage(
        sessionId,
        body,
        (ev) => {
          if (ev.event === "user_message") {
            setMessages((m) => [...m, ev.data as BuilderMessage]);
          } else if (ev.event === "graph_patch") {
            const d = ev.data as { ops?: PatchOp[]; graph?: Graph };
            if (d.graph) {
              useCanvas
                .getState()
                .replaceFromServer(normalizeGraph(d.graph), touchedNodeIds(d.ops ?? []));
            }
          } else if (ev.event === "done") {
            finished = true;
            setMessages((m) => [...m, ev.data as BuilderMessage]);
            setDraft((d) => (d?.error ? { ...emptyDraft(), error: d.error } : null));
          } else {
            setDraft((d) => reduceDraft(d ?? emptyDraft(), ev));
          }
        },
        ctrl.signal,
      );
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) setStreamError(err);
    } finally {
      setBusy(false);
      if (!finished) setDraft((d) => (d && (d.text || d.error || d.tool_calls.length) ? d : null));
      void qc.invalidateQueries({ queryKey: ["builder-messages", sessionId] });
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput("");
    void send({ content: text });
  };

  useEffect(() => {
    if (!appId) return;
    const t = window.setTimeout(() => {
      const p = takePendingPrompt(appId);
      if (p) void send({ content: p });
    }, 80);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appId]);

  const onInstall = (key: string) => {
    if (!key) return;
    install.mutate(key, {
      onSuccess: () => {
        toast.success("설치했어요.");
        void send({ content: "설치했어요", event: { type: "installed", item_key: key } });
      },
      onError: (err) => toast.error(err),
    });
  };

  const lastAssistantIdx = (() => {
    for (let i = messages.length - 1; i >= 0; i--) if (messages[i]?.role === "assistant") return i;
    return -1;
  })();

  const Bot = () => (
    <span className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-white">
      <Sparkles className="h-3.5 w-3.5" />
    </span>
  );

  return (
    <div className="flex h-full flex-col bg-white">
      <div className="flex h-12 items-center justify-between border-b border-slate-100 px-4">
        <p className="flex items-center gap-2 text-sm font-semibold text-slate-800">
          <Sparkles className="h-4 w-4 text-indigo-500" /> 빌더
        </p>
        {onNewSession && (
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 hover:text-slate-900"
            onClick={onNewSession}
            disabled={busy}
          >
            <RotateCcw className="h-3 w-3" /> 새 대화
          </button>
        )}
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4" aria-live="polite">
        {messages.length === 0 && !draft && (
          <div className="pt-6">
            <div className="flex justify-center">
              <span className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-lift">
                <Sparkles className="h-5 w-5" />
              </span>
            </div>
            <p className="mt-3 text-center text-[15px] font-semibold text-slate-800">
              무엇을 만들어 볼까요?
            </p>
            <p className="mt-1 text-center text-sm text-slate-500">
              말로 설명하면 오른쪽 캔버스에 흐름을 그려 드려요.
            </p>
            <div className="mt-5 space-y-2">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  className="block w-full rounded-xl border border-slate-200 px-3.5 py-2.5 text-left text-[13px] text-slate-600 transition-colors hover:border-indigo-300 hover:bg-indigo-50/60 hover:text-indigo-800"
                  onClick={() => void send({ content: ex })}
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={m.id} className="flex justify-end">
              <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-indigo-600 px-3.5 py-2 text-[14px] leading-relaxed text-white">
                {m.content.replace(/^\[알림\][^\n]*\n?/, "") || "설치했어요"}
              </p>
            </div>
          ) : (
            <div key={m.id} className="flex gap-2.5">
              <Bot />
              <div className="min-w-0 flex-1">
                <TurnBody
                  content={m.content}
                  record={m.graph_patch}
                  active={i === lastAssistantIdx && !draft}
                  busy={busy}
                  onPick={(o) => void send({ content: o })}
                  onInstall={onInstall}
                  installing={install.isPending}
                />
              </div>
            </div>
          ),
        )}
        {draft && (
          <div className="flex gap-2.5" data-testid="builder-draft">
            <Bot />
            <div className="min-w-0 flex-1">
              <TurnBody
                content={draft.text}
                record={draft}
                active
                busy={busy}
                onPick={(o) => void send({ content: o })}
                onInstall={onInstall}
                installing={install.isPending}
              />
              {draft.error && (
                <div
                  role="alert"
                  className="mt-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-2.5 text-sm"
                >
                  <p className="font-medium text-red-900">{draft.error.message}</p>
                  {draft.error.hint && <p className="text-red-700">{draft.error.hint}</p>}
                </div>
              )}
              {busy && !draft.text && draft.tool_calls.length === 0 && (
                <p className="flex items-center gap-1 pt-1.5 text-xs text-slate-400">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:120ms]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400 [animation-delay:240ms]" />
                </p>
              )}
            </div>
          </div>
        )}
        {streamError !== null && <ErrorBox error={streamError} />}
        <div ref={bottomRef} />
      </div>
      <form onSubmit={submit} className="p-3">
        <div className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-white p-1.5 pl-3 shadow-card focus-within:border-indigo-400 focus-within:ring-4 focus-within:ring-indigo-500/10">
          <textarea
            aria-label="빌더에게 보낼 메시지"
            className={cn(
              "max-h-40 min-h-[40px] flex-1 resize-none border-0 bg-transparent py-2 text-sm placeholder:text-slate-400 focus:outline-none",
            )}
            rows={1}
            placeholder={busy ? "빌더가 작업 중이에요…" : "더 바꾸고 싶은 걸 말해 주세요"}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            title={sendHint(enterToSend)}
            onKeyDown={(e) => {
              if (isSendKey(e, enterToSend)) {
                e.preventDefault();
                submit(e);
              }
            }}
          />
          <button
            type="submit"
            aria-label="보내기"
            disabled={busy || !input.trim()}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white transition-colors hover:bg-indigo-500 disabled:bg-slate-200 disabled:text-slate-400"
          >
            <ArrowUp className="h-4 w-4" />
          </button>
        </div>
        <p className="mt-1.5 px-1 text-[11px] text-slate-400">Enter 보내기 · Shift+Enter 줄바꿈</p>
      </form>
    </div>
  );
}

/** promptNonce가 바뀌면 대화를 다시 그려, 맡겨 둔 첫 메시지(예: 고쳐 달라는 요청)를 보낸다 */
export function BuilderChat({ appId, promptNonce = 0 }: { appId: string; promptNonce?: number }) {
  const wsId = useSession((s) => s.workspaceId);
  const qc = useQueryClient();
  const session = useBuilderSession(appId);
  const messages = useBuilderMessages(session.data?.id);

  const newSession = async () => {
    try {
      const s = await createBuilderSession(appId);
      qc.setQueryData(["builder-session", appId], s);
    } catch (err) {
      const { message } = errorLines(err);
      toast.error(err);
      console.warn(message);
    }
  };

  if (session.isLoading || messages.isLoading) return <Loading label="대화를 불러오는 중…" />;
  if (session.error || messages.error)
    return (
      <div className="p-4">
        <ErrorBox error={session.error ?? messages.error} />
      </div>
    );
  if (!session.data) return null;
  return (
    <BuilderChatView
      key={`${session.data.id}-${promptNonce}`}
      sessionId={session.data.id}
      appId={appId}
      history={messages.data ?? []}
      wsId={wsId}
      onNewSession={() => void newSession()}
    />
  );
}
