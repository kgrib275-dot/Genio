import { useEffect, useRef, useState, type FormEvent } from "react";
import { PageContainer } from "@/app/Layout";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Empty, PageHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import {
  searchKnowledgeBase,
  useCreateKnowledgeBase,
  useDeleteDocument,
  useDeleteKnowledgeBase,
  useDocuments,
  useKnowledgeBases,
  useUploadDocument,
} from "@/lib/api/resources";
import type { KnowledgeBase, SearchHit } from "@/lib/api/types";
import { cn, formatBytes, formatDate } from "@/lib/cn";
import { canEdit, useSession } from "@/store/session";

function KbDetail({ kb, editable }: { kb: KnowledgeBase; editable: boolean }) {
  const docs = useDocuments(kb.id);
  const upload = useUploadDocument(kb.id);
  const delDoc = useDeleteDocument(kb.id);
  const fileRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<unknown>(null);

  const search = async (e: FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setSearchError(null);
    try {
      setHits(await searchKnowledgeBase(kb.id, query));
    } catch (err) {
      setSearchError(err);
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={kb.name}
          description={`임베딩 모델 ${kb.embedding_model} · 조각 크기 ${kb.chunk_size}자`}
          action={
            editable && (
              <>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".pdf,.txt,.md,application/pdf,text/plain,text/markdown"
                  className="hidden"
                  aria-label="문서 파일"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f)
                      upload.mutate(f, {
                        onSuccess: () =>
                          toast.success("올렸어요. 처리가 끝나면 '준비됨'으로 바뀌어요."),
                        onError: (err) => toast.error(err),
                      });
                    e.target.value = "";
                  }}
                />
                <Button
                  size="sm"
                  disabled={upload.isPending}
                  onClick={() => fileRef.current?.click()}
                >
                  {upload.isPending ? "올리는 중…" : "+ 문서 올리기"}
                </Button>
              </>
            )
          }
        />
        <CardBody className="p-0">
          {docs.isLoading && <Loading />}
          <ErrorBox error={docs.error} />
          {docs.data?.length === 0 && (
            <p className="px-5 py-6 text-sm text-slate-500">
              PDF, TXT, MD 파일을 올리면 질문에 답할 때 써요.
            </p>
          )}
          <ul className="divide-y divide-slate-100">
            {(docs.data ?? []).map((d) => (
              <li key={d.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
                <span className="flex-1 truncate">{d.filename}</span>
                <span className="text-xs text-slate-400">{formatBytes(d.size)}</span>
                <span className="text-xs text-slate-400">조각 {d.chunk_count}</span>
                <StatusBadge status={d.status} />
                {d.error && (
                  <span className="max-w-[16rem] truncate text-xs text-red-600" title={d.error}>
                    {d.error}
                  </span>
                )}
                {editable && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-red-600"
                    onClick={() => delDoc.mutate(d.id)}
                  >
                    삭제
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>
      {editable && (
        <Card>
          <CardHeader
            title="검색 시험"
            description="질문하면 어떤 내용이 찾아지는지 미리 볼 수 있어요."
          />
          <CardBody className="space-y-3">
            <form onSubmit={search} className="flex gap-2">
              <Input
                aria-label="검색어"
                placeholder="예: 연차는 며칠인가요?"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <Button type="submit" disabled={searching}>
                검색
              </Button>
            </form>
            <ErrorBox error={searchError} />
            {hits?.length === 0 && <p className="text-sm text-slate-500">찾은 내용이 없어요.</p>}
            {hits?.map((h) => (
              <div key={h.chunk_id} className="rounded border border-slate-200 p-3 text-sm">
                <p className="mb-1 text-xs text-slate-500">
                  {h.filename} · 유사도 {h.score.toFixed(3)}
                </p>
                <p className="whitespace-pre-wrap">{h.content}</p>
              </div>
            ))}
          </CardBody>
        </Card>
      )}
    </div>
  );
}

export default function KnowledgePage() {
  const { workspaceId: ws, role } = useSession();
  const kbs = useKnowledgeBases(ws);
  const create = useCreateKnowledgeBase(ws);
  const del = useDeleteKnowledgeBase(ws);
  const [selected, setSelected] = useState<string>("");
  const [name, setName] = useState("");
  const editable = canEdit(role);

  useEffect(() => {
    const list = kbs.data ?? [];
    if (list.length && !list.some((k) => k.id === selected) && list[0]) setSelected(list[0].id);
  }, [kbs.data, selected]);

  const kb = (kbs.data ?? []).find((k) => k.id === selected);

  return (
    <PageContainer>
      <PageHeader title="지식베이스" description="문서를 올려 두면 챗봇이 그 내용으로 답해요." />
      <ErrorBox error={kbs.error} />
      <div className="grid gap-6 md:grid-cols-[260px_1fr]">
        <div className="space-y-3">
          {editable && (
            <form
              className="space-y-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (!name.trim()) return;
                create.mutate(
                  { name },
                  {
                    onSuccess: (k) => {
                      setName("");
                      setSelected(k.id);
                    },
                  },
                );
              }}
            >
              <Field label="새 지식베이스" htmlFor="kb-name">
                <Input
                  id="kb-name"
                  placeholder="예: 사내 규정"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </Field>
              <ErrorBox error={create.error} />
              <Button type="submit" size="sm" disabled={create.isPending || !name.trim()}>
                만들기
              </Button>
            </form>
          )}
          {kbs.isLoading && <Loading />}
          <ul className="space-y-1">
            {(kbs.data ?? []).map((k) => (
              <li key={k.id} className="group flex items-center">
                <button
                  type="button"
                  onClick={() => setSelected(k.id)}
                  className={cn(
                    "flex-1 rounded-md px-3 py-2 text-left text-sm",
                    k.id === selected
                      ? "bg-indigo-50 font-medium text-indigo-700"
                      : "hover:bg-slate-100",
                  )}
                >
                  {k.name}
                  <span className="ml-1 text-xs text-slate-400">({k.document_count})</span>
                  <span className="block text-[11px] text-slate-400">
                    {formatDate(k.created_at)}
                  </span>
                </button>
                {editable && (
                  <button
                    type="button"
                    aria-label={`${k.name} 삭제`}
                    className="invisible px-2 text-xs text-red-500 group-hover:visible"
                    onClick={() => {
                      if (window.confirm(`'${k.name}'을(를) 지울까요? 올린 문서도 함께 지워져요.`))
                        del.mutate(k.id);
                    }}
                  >
                    삭제
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
        <div>
          {kb ? (
            <KbDetail key={kb.id} kb={kb} editable={editable} />
          ) : (
            kbs.data && <Empty>지식베이스를 만들고 문서를 올려 보세요.</Empty>
          )}
        </div>
      </div>
    </PageContainer>
  );
}
