import {
  ArrowLeft,
  History,
  MessageSquarePlus,
  Pencil,
  ShieldBan,
  StickyNote,
  ThumbsDown,
  ThumbsUp,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, Empty } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Textarea } from "@/components/ui/input";
import { Tabs } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toast-store";
import { useApp } from "@/lib/api/apps";
import type { Annotation, ConversationMessage, Rating } from "@/lib/api/types";
import {
  useAnnotations,
  useConversationMessages,
  useConversations,
  useCreateAnnotation,
  useDeleteAnnotation,
  useUpdateAnnotation,
} from "@/lib/api/v2";
import { cn, formatDate, timeAgo } from "@/lib/cn";
import { AppNav } from "@/pages/apps/AppNav";
import { canEdit, useSession } from "@/store/session";

function ratingOf(m: ConversationMessage): Rating | null {
  const f = m.feedback;
  if (!f) return null;
  if (typeof f === "string") return f;
  return f.rating ?? null;
}

function AnnotationDialog({
  appId,
  open,
  onClose,
  initial,
}: {
  appId: string;
  open: boolean;
  onClose: () => void;
  initial: { id?: string; question: string; answer: string };
}) {
  const create = useCreateAnnotation(appId);
  const update = useUpdateAnnotation(appId);
  const [q, setQ] = useState(initial.question);
  const [a, setA] = useState(initial.answer);
  const busy = create.isPending || update.isPending;
  const submit = () => {
    const opts = {
      onSuccess: () => {
        toast.success("주석을 저장했어요.");
        onClose();
      },
      onError: (err: unknown) => toast.error(err),
    };
    if (initial.id) update.mutate({ id: initial.id, question: q, answer: a }, opts);
    else create.mutate({ question: q, answer: a }, opts);
  };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={initial.id ? "주석 고치기" : "주석 추가"}
      wide
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            취소
          </Button>
          <Button disabled={busy || !q.trim() || !a.trim()} onClick={submit}>
            저장
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="질문" htmlFor="ann-q">
          <Textarea id="ann-q" value={q} onChange={(e) => setQ(e.target.value)} />
        </Field>
        <Field
          label="정해 둔 답"
          htmlFor="ann-a"
          hint="앱 기능에서 '주석 답변'을 켜면, 비슷한 질문에 AI 대신 이 답을 바로 보내요."
        >
          <Textarea
            id="ann-a"
            className="min-h-[120px]"
            value={a}
            onChange={(e) => setA(e.target.value)}
          />
        </Field>
      </div>
    </Dialog>
  );
}

function ConversationView({
  appId,
  conversationId,
  onBack,
  editable,
}: {
  appId: string;
  conversationId: string;
  onBack: () => void;
  editable: boolean;
}) {
  const msgs = useConversationMessages(conversationId);
  const [draft, setDraft] = useState<{ question: string; answer: string } | null>(null);
  const list = msgs.data ?? [];
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
        <Button size="sm" variant="ghost" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" /> 목록
        </Button>
        <p className="text-sm font-semibold">대화 내용</p>
      </div>
      <div className="space-y-3 bg-slate-50/60 px-4 py-4">
        {msgs.isLoading && <Loading />}
        <ErrorBox error={msgs.error} />
        {list.map((m, i) => {
          const rating = ratingOf(m);
          const prevUser = [...list.slice(0, i)].reverse().find((x) => x.role === "user");
          return (
            <div
              key={m.id}
              className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}
            >
              <div className="max-w-[88%] space-y-1">
                <div
                  className={cn(
                    "whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm",
                    m.role === "user"
                      ? "rounded-br-md bg-indigo-600 text-white"
                      : "rounded-bl-md border border-slate-200 bg-white text-slate-800",
                  )}
                >
                  {m.content}
                </div>
                <div
                  className={cn(
                    "flex flex-wrap items-center gap-1.5 text-[11px] text-slate-400",
                    m.role === "user" && "justify-end",
                  )}
                >
                  <span>{formatDate(m.created_at)}</span>
                  {m.annotated && <Badge tone="indigo">주석 답변</Badge>}
                  {m.moderated && (
                    <Badge tone="amber">
                      <ShieldBan className="h-3 w-3" /> 검열됨
                    </Badge>
                  )}
                  {rating === "like" && (
                    <Badge tone="green">
                      <ThumbsUp className="h-3 w-3" /> 좋아요
                    </Badge>
                  )}
                  {rating === "dislike" && (
                    <Badge tone="red">
                      <ThumbsDown className="h-3 w-3" /> 싫어요
                    </Badge>
                  )}
                  {m.run_id && (
                    <Link to={`/runs/${m.run_id}`} className="hover:text-indigo-600">
                      실행 보기
                    </Link>
                  )}
                  {editable && m.role === "assistant" && (
                    <button
                      type="button"
                      className="inline-flex items-center gap-0.5 font-medium text-indigo-600 hover:underline"
                      onClick={() =>
                        setDraft({ question: prevUser?.content ?? "", answer: m.content })
                      }
                    >
                      <MessageSquarePlus className="h-3 w-3" /> 주석으로 추가
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
        {msgs.data && list.length === 0 && (
          <p className="text-sm text-slate-500">메시지가 없어요.</p>
        )}
      </div>
      {draft && (
        <AnnotationDialog appId={appId} open onClose={() => setDraft(null)} initial={draft} />
      )}
    </Card>
  );
}

function Conversations({ appId, editable }: { appId: string; editable: boolean }) {
  const [page, setPage] = useState(1);
  const convs = useConversations(appId, page);
  const [open, setOpen] = useState<string | null>(null);
  if (open)
    return (
      <ConversationView
        appId={appId}
        conversationId={open}
        onBack={() => setOpen(null)}
        editable={editable}
      />
    );
  const list = convs.data ?? [];
  return (
    <div className="space-y-3">
      {convs.isLoading && <Loading />}
      <ErrorBox error={convs.error} />
      {convs.data && list.length === 0 && page === 1 && (
        <Empty>아직 대화가 없어요. 배포한 링크나 위젯으로 대화가 오가면 여기에 쌓여요.</Empty>
      )}
      {list.length > 0 && (
        <Card className="overflow-hidden">
          <ul className="divide-y divide-slate-100">
            {list.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => setOpen(c.id)}
                  className="flex w-full flex-col gap-1 px-4 py-3 text-left hover:bg-slate-50 sm:flex-row sm:items-center sm:gap-3"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-slate-800">
                      {c.first_question || "(첫 질문 없음)"}
                    </span>
                    <span className="block text-xs text-slate-500">
                      {c.user_name || "익명"} · 메시지 {c.message_count}개
                    </span>
                  </span>
                  <span className="flex items-center gap-2 text-xs text-slate-400">
                    {c.likes > 0 && (
                      <span className="inline-flex items-center gap-0.5 text-emerald-600">
                        <ThumbsUp className="h-3 w-3" /> {c.likes}
                      </span>
                    )}
                    {c.dislikes > 0 && (
                      <span className="inline-flex items-center gap-0.5 text-red-600">
                        <ThumbsDown className="h-3 w-3" /> {c.dislikes}
                      </span>
                    )}
                    {timeAgo(c.last_message_at ?? c.created_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {(page > 1 || list.length >= 20) && (
        <div className="flex justify-center gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            이전
          </Button>
          <span className="self-center text-xs text-slate-500">{page}쪽</span>
          <Button
            size="sm"
            variant="outline"
            disabled={list.length < 20}
            onClick={() => setPage(page + 1)}
          >
            다음
          </Button>
        </div>
      )}
    </div>
  );
}

function Annotations({ appId, editable }: { appId: string; editable: boolean }) {
  const list = useAnnotations(appId);
  const del = useDeleteAnnotation(appId);
  const [editing, setEditing] = useState<Partial<Annotation> | null>(null);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-slate-500">
          비슷한 질문이 오면 AI를 거치지 않고 정해 둔 답을 보내요(앱 기능에서 켜기).
        </p>
        {editable && (
          <Button size="sm" onClick={() => setEditing({ question: "", answer: "" })}>
            <MessageSquarePlus className="h-4 w-4" /> 주석 추가
          </Button>
        )}
      </div>
      {list.isLoading && <Loading />}
      <ErrorBox error={list.error} />
      {list.data?.length === 0 && <Empty>아직 주석이 없어요.</Empty>}
      <div className="grid gap-3 md:grid-cols-2">
        {(list.data ?? []).map((a) => (
          <Card key={a.id} className="p-4">
            <p className="text-xs font-semibold text-slate-400">질문</p>
            <p className="whitespace-pre-wrap text-sm text-slate-800">{a.question}</p>
            <p className="mt-2 text-xs font-semibold text-slate-400">답</p>
            <p className="whitespace-pre-wrap text-sm text-slate-700">{a.answer}</p>
            <div className="mt-3 flex items-center gap-2 text-xs text-slate-400">
              <span>{a.hit_count}번 쓰임</span>
              <span>· {formatDate(a.created_at)}</span>
              {editable && (
                <span className="ml-auto flex gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="주석 고치기"
                    onClick={() => setEditing(a)}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-red-600"
                    aria-label="주석 지우기"
                    onClick={() => {
                      if (window.confirm("이 주석을 지울까요?"))
                        del.mutate(a.id, { onError: (err) => toast.error(err) });
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </span>
              )}
            </div>
          </Card>
        ))}
      </div>
      {editing && (
        <AnnotationDialog
          appId={appId}
          open
          onClose={() => setEditing(null)}
          initial={{
            id: editing.id,
            question: editing.question ?? "",
            answer: editing.answer ?? "",
          }}
        />
      )}
    </div>
  );
}

export default function AppLogsPage() {
  const { id: appId = "" } = useParams();
  const role = useSession((s) => s.role);
  const app = useApp(appId);
  const [tab, setTab] = useState<"conversations" | "annotations">("conversations");
  const editable = canEdit(role);
  return (
    <div className="flex min-h-full flex-col">
      <AppNav appId={appId} title={app.data?.name ?? ""} icon={app.data?.icon} help="logs" />
      <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Tabs
            value={tab}
            onChange={setTab}
            items={[
              { value: "conversations", label: "대화" },
              ...(editable ? [{ value: "annotations" as const, label: "주석" }] : []),
            ]}
          />
          <Link
            to={`/apps/${appId}/runs`}
            className="mb-5 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-indigo-600"
          >
            <History className="h-4 w-4" /> 실행 기록
          </Link>
        </div>
        {tab === "conversations" ? (
          <Conversations appId={appId} editable={editable} />
        ) : (
          <Annotations appId={appId} editable={editable} />
        )}
        <p className="mt-6 flex items-center gap-1 text-xs text-slate-400">
          <StickyNote className="h-3.5 w-3.5" /> 로그에는 배포한 링크·위젯·API로 오간 대화가 쌓여요.
        </p>
      </div>
    </div>
  );
}
