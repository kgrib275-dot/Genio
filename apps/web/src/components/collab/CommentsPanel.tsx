// 캔버스 댓글 패널(v0.9): 단계·캔버스 위치에 단 댓글을 스레드로 보고, 남기고, 해결 처리한다.
import {
  Check,
  CornerDownRight,
  MapPin,
  MessageSquare,
  Pencil,
  RotateCcw,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast-store";
import {
  useCollaborators,
  useComments,
  useCreateComment,
  useDeleteComment,
  useEditComment,
  useResolveComment,
  type Collaborator,
  type CommentItem,
  type CommentThread,
} from "@/lib/api/collab";
import { cn } from "@/lib/cn";
import {
  extractMentionIds,
  filterPeople,
  filterThreads,
  mentionQuery,
  pickMention,
  timeAgo,
  type StatusFilter,
} from "@/lib/commentsUi";
import { useCanvas } from "@/store/canvas";
import { useCollab } from "@/store/collab";

const STATUS_LABEL: Record<StatusFilter, string> = { open: "열림", resolved: "해결", all: "전체" };

/** 본문 속 '@이름'을 눈에 띄게. */
function Body({ text, names }: { text: string; names: string[] }): ReactNode {
  if (!names.length) return text;
  const esc = names
    .map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .sort((a, b) => b.length - a.length);
  const parts = text.split(new RegExp(`(@(?:${esc.join("|")}))`, "g"));
  return parts.map((p, i) =>
    p.startsWith("@") && names.includes(p.slice(1)) ? (
      <b key={i} className="rounded bg-indigo-50 px-0.5 font-semibold text-indigo-700">
        {p}
      </b>
    ) : (
      <span key={i}>{p}</span>
    ),
  );
}

/** @로 사람을 부를 수 있는 입력칸. ↑↓ Enter로 고르고 Esc로 닫는다. */
function MentionBox({
  value,
  onChange,
  people,
  placeholder,
  onSubmit,
  autoFocus,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  people: Collaborator[];
  placeholder: string;
  onSubmit: () => void;
  autoFocus?: boolean;
  label: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const [caret, setCaret] = useState(0);
  const [active, setActive] = useState(0);
  const [closed, setClosed] = useState(false);
  const q = closed ? null : mentionQuery(value, caret);
  const options = q ? filterPeople(people, q.query) : [];
  useEffect(() => setActive(0), [q?.query]);

  const pick = (p: Collaborator) => {
    const r = pickMention(value, caret, p.name);
    if (!r) return;
    onChange(r.text);
    requestAnimationFrame(() => {
      ref.current?.focus();
      ref.current?.setSelectionRange(r.caret, r.caret);
      setCaret(r.caret);
    });
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (options.length) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        setActive((a) => (a + (e.key === "ArrowDown" ? 1 : options.length - 1)) % options.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        const o = options[active];
        if (o) pick(o);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setClosed(true);
        return;
      }
    }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      onSubmit();
    }
  };
  return (
    <div className="relative">
      <textarea
        ref={ref}
        aria-label={label}
        autoFocus={autoFocus}
        value={value}
        rows={3}
        maxLength={2000}
        placeholder={placeholder}
        onChange={(e) => {
          onChange(e.target.value);
          setCaret(e.target.selectionStart);
          setClosed(false);
        }}
        onSelect={(e) => setCaret(e.currentTarget.selectionStart)}
        onKeyDown={onKeyDown}
        className="w-full resize-none rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
      />
      {options.length > 0 && (
        <ul
          role="listbox"
          aria-label="멘션할 사람"
          className="absolute bottom-full left-0 z-20 mb-1 w-full overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lift"
        >
          {options.map((p, i) => (
            <li key={p.id} role="option" aria-selected={i === active}>
              <button
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(p);
                }}
                className={cn(
                  "flex w-full items-center justify-between px-2.5 py-1.5 text-left text-sm",
                  i === active
                    ? "bg-indigo-50 text-indigo-800"
                    : "text-slate-700 hover:bg-slate-50",
                )}
              >
                <span>{p.name}</span>
                <span className="text-[11px] text-slate-400">{p.role}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1 text-[11px] text-slate-400">@로 사람을 부르고, Ctrl+Enter로 보내요.</p>
    </div>
  );
}

function Composer({
  appId,
  people,
  parentId,
  nodeId,
  x,
  y,
  placeholder,
  onDone,
  autoFocus,
}: {
  appId: string;
  people: Collaborator[];
  parentId?: string;
  nodeId?: string | null;
  x?: number | null;
  y?: number | null;
  placeholder: string;
  onDone: () => void;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState("");
  const create = useCreateComment(appId);
  const submit = () => {
    const body = text.trim();
    if (!body || create.isPending) return;
    create.mutate(
      {
        body,
        parent_id: parentId ?? null,
        node_id: nodeId ?? null,
        x: x ?? null,
        y: y ?? null,
        mentions: extractMentionIds(body, people),
      },
      {
        onSuccess: (t) => {
          setText("");
          onDone();
          useCollab.getState().focusThread(t.id);
        },
        onError: (err) => toast.error(err),
      },
    );
  };
  return (
    <div className="space-y-1.5">
      <MentionBox
        value={text}
        onChange={setText}
        people={people}
        placeholder={placeholder}
        onSubmit={submit}
        autoFocus={autoFocus}
        label={parentId ? "답글 쓰기" : "댓글 쓰기"}
      />
      <div className="flex justify-end gap-1.5">
        <Button size="sm" variant="ghost" onClick={onDone}>
          취소
        </Button>
        <Button size="sm" disabled={!text.trim() || create.isPending} onClick={submit}>
          {parentId ? "답글 남기기" : "남기기"}
        </Button>
      </div>
    </div>
  );
}

function Entry({
  c,
  appId,
  people,
  me,
  canDeleteAny,
  canWrite,
}: {
  c: CommentItem;
  appId: string;
  people: Collaborator[];
  me: string;
  canDeleteAny: boolean;
  canWrite: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(c.body);
  const edit = useEditComment(appId);
  const del = useDeleteComment(appId);
  const mine = c.author.id === me;
  const names = c.mentions.map((m) => m.name);
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5 text-xs">
        <span className="font-semibold text-slate-800">{c.author.name}</span>
        <span className="text-slate-400">
          {timeAgo(c.created_at)}
          {c.edited_at ? " · 고침" : ""}
        </span>
        {canWrite && (mine || canDeleteAny) && !editing && (
          <span className="ml-auto flex gap-0.5">
            {mine && (
              <button
                type="button"
                aria-label="댓글 고치기"
                onClick={() => setEditing(true)}
                className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              >
                <Pencil className="h-3 w-3" />
              </button>
            )}
            <button
              type="button"
              aria-label="댓글 지우기"
              onClick={() => {
                if (window.confirm("이 댓글을 지울까요? 달린 답글도 함께 사라져요."))
                  del.mutate(c.id, { onError: (err) => toast.error(err) });
              }}
              className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </span>
        )}
      </div>
      {editing ? (
        <div className="space-y-1.5">
          <MentionBox
            value={text}
            onChange={setText}
            people={people}
            placeholder="댓글 고치기"
            label="댓글 고치기"
            autoFocus
            onSubmit={() => undefined}
          />
          <div className="flex justify-end gap-1.5">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setEditing(false);
                setText(c.body);
              }}
            >
              취소
            </Button>
            <Button
              size="sm"
              disabled={!text.trim() || edit.isPending}
              onClick={() =>
                edit.mutate(
                  { id: c.id, body: text.trim(), mentions: extractMentionIds(text, people) },
                  { onSuccess: () => setEditing(false), onError: (err) => toast.error(err) },
                )
              }
            >
              저장
            </Button>
          </div>
        </div>
      ) : (
        <p className="whitespace-pre-wrap break-words text-[13px] leading-snug text-slate-700">
          <Body text={c.body} names={names} />
        </p>
      )}
    </div>
  );
}

function Thread({
  t,
  appId,
  people,
  me,
  nodeLabel,
  canWrite,
  canDeleteAny,
  focused,
}: {
  t: CommentThread;
  appId: string;
  people: Collaborator[];
  me: string;
  nodeLabel: string | null;
  canWrite: boolean;
  canDeleteAny: boolean;
  focused: boolean;
}) {
  const [replying, setReplying] = useState(false);
  const resolve = useResolveComment(appId);
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [focused]);
  return (
    <article
      ref={ref}
      data-testid={`thread-${t.id}`}
      className={cn(
        "space-y-2 rounded-xl border p-2.5",
        focused ? "border-indigo-400 ring-2 ring-indigo-500/15" : "border-slate-200",
        t.resolved && "opacity-70",
      )}
    >
      <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
        {t.node_id ? (
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 hover:bg-indigo-50 hover:text-indigo-700"
            onClick={() =>
              useCanvas.getState().setSelection(nodeLabel ? [t.node_id as string] : [])
            }
          >
            <MessageSquare className="h-3 w-3" /> {nodeLabel ?? "지워진 단계"}
          </button>
        ) : (
          <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5">
            <MapPin className="h-3 w-3" /> 캔버스 위치
          </span>
        )}
        {t.resolved && (
          <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700">
            해결됨{t.resolved_by ? ` · ${t.resolved_by}` : ""}
          </span>
        )}
        {canWrite && (
          <button
            type="button"
            onClick={() =>
              resolve.mutate(
                { id: t.id, resolved: !t.resolved },
                { onError: (err) => toast.error(err) },
              )
            }
            className="ml-auto inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
          >
            {t.resolved ? (
              <>
                <RotateCcw className="h-3 w-3" /> 다시 열기
              </>
            ) : (
              <>
                <Check className="h-3 w-3" /> 해결
              </>
            )}
          </button>
        )}
      </div>
      <Entry
        c={t}
        appId={appId}
        people={people}
        me={me}
        canDeleteAny={canDeleteAny}
        canWrite={canWrite}
      />
      {t.replies.length > 0 && (
        <div className="space-y-2 border-l-2 border-slate-100 pl-2.5">
          {t.replies.map((r) => (
            <Entry
              key={r.id}
              c={r}
              appId={appId}
              people={people}
              me={me}
              canDeleteAny={canDeleteAny}
              canWrite={canWrite}
            />
          ))}
        </div>
      )}
      {canWrite &&
        (replying ? (
          <Composer
            appId={appId}
            people={people}
            parentId={t.id}
            placeholder="답글을 적어 주세요"
            onDone={() => setReplying(false)}
            autoFocus
          />
        ) : (
          <button
            type="button"
            onClick={() => setReplying(true)}
            className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800"
          >
            <CornerDownRight className="h-3 w-3" /> 답글
          </button>
        ))}
    </article>
  );
}

export function CommentsPanel({
  appId,
  canWrite,
  canDeleteAny,
  onClose,
}: {
  appId: string;
  canWrite: boolean;
  canDeleteAny: boolean;
  onClose: () => void;
}) {
  const threads = useComments(appId);
  const people = useCollaborators(appId).data ?? [];
  const me = useCollab((s) => s.me);
  const compose = useCollab((s) => s.compose);
  const focusId = useCollab((s) => s.focusThreadId);
  const commentMode = useCollab((s) => s.commentMode);
  const selectedId = useCanvas((s) => s.selectedId);
  const nodes = useCanvas((s) => s.graph.nodes);
  const [status, setStatus] = useState<StatusFilter>("open");
  const [onlySelected, setOnlySelected] = useState(false);

  const labelOf = useMemo(() => {
    const m = new Map(
      nodes.map((n) => [n.id, String((n.data as { label?: string }).label ?? n.type)]),
    );
    return (id: string | null) => (id ? (m.get(id) ?? null) : null);
  }, [nodes]);

  // 새로 남긴 스레드가 지금 거르는 조건에서 안 보이면 조건을 풀어 준다
  useEffect(() => {
    if (!focusId || !threads.data) return;
    const t = threads.data.find((x) => x.id === focusId);
    if (t && status !== "all" && (t.resolved ? "resolved" : "open") !== status) setStatus("all");
  }, [focusId, threads.data, status]);

  const shown = filterThreads(threads.data ?? [], {
    status,
    nodeId: onlySelected ? selectedId : null,
  });
  const targetLabel = compose?.nodeId
    ? `'${labelOf(compose.nodeId) ?? "단계"}' 단계에`
    : "캔버스 이 위치에";

  return (
    <aside
      aria-label="댓글"
      className="flex h-full min-h-0 w-full flex-col border-l border-slate-200 bg-white"
    >
      <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2.5">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
          <MessageSquare className="h-4 w-4 text-indigo-500" /> 댓글
          <span className="text-xs font-normal text-slate-400">{threads.data?.length ?? 0}</span>
        </h2>
        <button
          type="button"
          aria-label="댓글 닫기"
          onClick={onClose}
          className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="space-y-2 border-b border-slate-100 px-3 py-2">
        <div
          role="radiogroup"
          aria-label="댓글 거르기"
          className="inline-flex rounded-lg bg-slate-100 p-0.5"
        >
          {(Object.keys(STATUS_LABEL) as StatusFilter[]).map((s) => (
            <button
              key={s}
              type="button"
              role="radio"
              aria-checked={status === s}
              onClick={() => setStatus(s)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs",
                status === s ? "bg-white font-semibold text-slate-900 shadow-sm" : "text-slate-500",
              )}
            >
              {STATUS_LABEL[s]}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1.5 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={onlySelected}
            disabled={!selectedId}
            onChange={(e) => setOnlySelected(e.target.checked)}
            className="accent-indigo-600"
          />
          고른 단계의 댓글만
        </label>
        {canWrite && (
          <div className="flex flex-wrap gap-1.5">
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                useCollab.getState().openCompose({ nodeId: selectedId, x: null, y: null })
              }
              disabled={!selectedId}
              title={selectedId ? "" : "캔버스에서 단계를 먼저 누르세요"}
            >
              <MessageSquare className="h-3.5 w-3.5" /> 고른 단계에 댓글
            </Button>
            <Button
              size="sm"
              variant={commentMode ? "primary" : "outline"}
              aria-pressed={commentMode}
              onClick={() => useCollab.getState().setCommentMode(!commentMode)}
            >
              <MapPin className="h-3.5 w-3.5" />{" "}
              {commentMode ? "핀 꽂는 중(캔버스를 누르세요)" : "캔버스에 핀 꽂기"}
            </Button>
          </div>
        )}
      </div>
      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-3">
        {compose && canWrite && (
          <div className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-2.5">
            <p className="mb-1.5 text-xs font-medium text-indigo-800">
              {targetLabel} 댓글을 남겨요
            </p>
            <Composer
              appId={appId}
              people={people}
              nodeId={compose.nodeId}
              x={compose.x}
              y={compose.y}
              placeholder="무엇이든 적어 주세요. @로 사람을 부를 수 있어요."
              onDone={() => useCollab.getState().openCompose(null)}
              autoFocus
            />
          </div>
        )}
        {threads.isLoading && <p className="text-sm text-slate-500">불러오는 중…</p>}
        {!threads.isLoading && shown.length === 0 && !compose && (
          <p className="rounded-lg bg-slate-50 px-3 py-4 text-center text-sm text-slate-500">
            {status === "open"
              ? "열려 있는 댓글이 없어요."
              : status === "resolved"
                ? "해결된 댓글이 없어요."
                : "아직 댓글이 없어요."}
            {canWrite && (
              <span className="mt-1 block text-xs">
                단계를 누르고 '고른 단계에 댓글'로 시작해 보세요.
              </span>
            )}
          </p>
        )}
        {shown.map((t) => (
          <Thread
            key={t.id}
            t={t}
            appId={appId}
            people={people}
            me={me}
            nodeLabel={labelOf(t.node_id)}
            canWrite={canWrite}
            canDeleteAny={canDeleteAny}
            focused={t.id === focusId}
          />
        ))}
      </div>
    </aside>
  );
}
