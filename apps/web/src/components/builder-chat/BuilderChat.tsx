import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  AskUserCard,
  MarketSuggestionCard,
  TestResultCard,
  ToolCallCard,
} from "@/components/builder-chat/cards";
import { emptyDraft, reduceDraft, type DraftTurn } from "@/components/builder-chat/turn";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
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
import { touchedNodeIds, useCanvas } from "@/store/canvas";
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
      {(record?.tool_calls ?? []).length > 0 && (
        <div className="space-y-1">
          {record?.tool_calls?.map((c) => (
            <ToolCallCard key={c.id} call={c} />
          ))}
        </div>
      )}
      {content && <p className="whitespace-pre-wrap text-sm text-slate-900">{content}</p>}
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
  history: BuilderMessage[];
  wsId: string;
  onNewSession?: () => void;
}

/** 빌더 챗 본체. 세션과 이전 메시지를 받아서 대화를 이어 간다. */
export function BuilderChatView({ sessionId, history, wsId, onNewSession }: BuilderChatViewProps) {
  const [messages, setMessages] = useState<BuilderMessage[]>(history);
  const [draft, setDraft] = useState<DraftTurn | null>(null);
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState("");
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

  return (
    <div className="flex h-full flex-col bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
        <p className="text-sm font-semibold">빌더와 대화</p>
        {onNewSession && (
          <button
            type="button"
            className="text-xs text-slate-500 hover:text-slate-900"
            onClick={onNewSession}
            disabled={busy}
          >
            새 대화
          </button>
        )}
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3" aria-live="polite">
        {messages.length === 0 && !draft && (
          <div className="space-y-2">
            <p className="text-sm text-slate-600">
              만들고 싶은 앱을 말로 설명해 주세요. 빌더가 오른쪽 캔버스에 흐름을 만들어 드려요.
            </p>
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                className="block w-full rounded-md border border-slate-200 px-3 py-2 text-left text-sm text-slate-700 hover:border-indigo-300 hover:bg-indigo-50"
                onClick={() => void send({ content: ex })}
              >
                {ex}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={m.id} className="flex justify-end">
              <p className="max-w-[85%] whitespace-pre-wrap rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white">
                {m.content}
              </p>
            </div>
          ) : (
            <div key={m.id} className="max-w-[95%]">
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
          ),
        )}
        {draft && (
          <div className="max-w-[95%]" data-testid="builder-draft">
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
                className="mt-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm"
              >
                <p className="font-medium text-red-900">{draft.error.message}</p>
                {draft.error.hint && <p className="text-red-700">{draft.error.hint}</p>}
              </div>
            )}
            {busy && <p className="mt-1 text-xs text-slate-400">빌더가 작업하고 있어요…</p>}
          </div>
        )}
        {streamError !== null && <ErrorBox error={streamError} />}
        <div ref={bottomRef} />
      </div>
      <form onSubmit={submit} className="border-t border-slate-200 p-3">
        <div className="flex gap-2">
          <textarea
            aria-label="빌더에게 보낼 메시지"
            className={cn(
              "min-h-[44px] flex-1 resize-none rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none",
            )}
            rows={2}
            placeholder="예: 두 번째 노드 창의성을 낮춰 줘"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit(e);
              }
            }}
          />
          <Button type="submit" disabled={busy || !input.trim()}>
            보내기
          </Button>
        </div>
      </form>
    </div>
  );
}

export function BuilderChat({ appId }: { appId: string }) {
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
      key={session.data.id}
      sessionId={session.data.id}
      history={messages.data ?? []}
      wsId={wsId}
      onNewSession={() => void newSession()}
    />
  );
}
