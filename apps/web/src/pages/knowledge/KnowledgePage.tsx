import {
  FileText,
  Globe,
  Layers,
  RefreshCw,
  Search,
  Settings2,
  Tags,
  Trash2,
  Upload,
} from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { PageContainer } from "@/app/Layout";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Empty, PageHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { HelpButton } from "@/help/HelpButton";
import {
  useCreateKnowledgeBase,
  useDeleteDocument,
  useDeleteKnowledgeBase,
  useDocuments,
  useKnowledgeBases,
  useUploadDocument,
} from "@/lib/api/resources";
import {
  normalizeKbSettings,
  type KbDocumentV2,
  type KnowledgeBaseV2,
  type RetrievalMethod,
  type SearchHitV2,
} from "@/lib/api/types";
import { searchKnowledgeBaseV2, useReprocessDocument } from "@/lib/api/v2";
import { cn, formatBytes, formatDate } from "@/lib/cn";
import {
  ChunksDialog,
  KbSettingsDialog,
  MetadataDialog,
  UrlImportDialog,
} from "@/pages/knowledge/KbDialogs";
import { canEdit, useSession } from "@/store/session";

const METHOD_LABEL: Record<RetrievalMethod, string> = {
  vector: "의미",
  keyword: "낱말",
  hybrid: "혼합",
};

function parseFilter(text: string): Record<string, string> | undefined {
  const pairs: [string, string][] = [];
  for (const part of text.split(/[,\n]/)) {
    const [k, v] = part.split("=");
    if (k?.trim() && v !== undefined) pairs.push([k.trim(), v.trim()]);
  }
  return pairs.length ? Object.fromEntries(pairs) : undefined;
}

function DocRow({
  d,
  editable,
  onChunks,
  onMeta,
  onReprocess,
  onDelete,
  reprocessing,
}: {
  d: KbDocumentV2;
  editable: boolean;
  onChunks: () => void;
  onMeta: () => void;
  onReprocess: () => void;
  onDelete: () => void;
  reprocessing: boolean;
}) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-3 text-sm sm:px-5">
      <span className="flex min-w-0 flex-1 basis-48 items-center gap-1.5">
        {d.source === "url" ? (
          <Globe className="h-3.5 w-3.5 shrink-0 text-slate-400" />
        ) : (
          <FileText className="h-3.5 w-3.5 shrink-0 text-slate-400" />
        )}
        <span className="truncate" title={d.url ?? d.filename}>
          {d.filename}
        </span>
      </span>
      {Object.entries(d.metadata ?? {}).map(([k, v]) => (
        <Badge key={k} tone="blue">
          {k}={v}
        </Badge>
      ))}
      <span className="text-xs text-slate-400">
        {formatBytes(d.size)} · 조각 {d.chunk_count}
      </span>
      <StatusBadge status={d.status} />
      {d.error && (
        <span className="basis-full text-xs text-red-600" title={d.error}>
          {d.error}
        </span>
      )}
      <span className="ml-auto flex shrink-0 gap-0.5">
        <Button
          size="sm"
          variant="ghost"
          aria-label="조각 보기"
          title="조각 보기"
          onClick={onChunks}
        >
          <Layers className="h-3.5 w-3.5" />
        </Button>
        {editable && (
          <>
            <Button size="sm" variant="ghost" aria-label="꼬리표" title="꼬리표" onClick={onMeta}>
              <Tags className="h-3.5 w-3.5" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label="다시 나누기"
              title="다시 나누기(설정 반영)"
              disabled={reprocessing || d.status === "processing"}
              onClick={onReprocess}
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-red-600"
              aria-label="문서 삭제"
              title="삭제"
              onClick={onDelete}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </>
        )}
      </span>
    </li>
  );
}

function SearchCard({ kb }: { kb: KnowledgeBaseV2 }) {
  const settings = normalizeKbSettings(kb.settings);
  const [query, setQuery] = useState("");
  const [method, setMethod] = useState<RetrievalMethod>(settings.retrieval.method);
  const [threshold, setThreshold] = useState(settings.retrieval.score_threshold);
  const [filterText, setFilterText] = useState("");
  const [hits, setHits] = useState<SearchHitV2[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<unknown>(null);

  const search = async (e: FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setSearchError(null);
    try {
      setHits(
        await searchKnowledgeBaseV2(kb.id, {
          query,
          top_k: settings.retrieval.top_k,
          method,
          score_threshold: threshold,
          metadata_filter: parseFilter(filterText),
        }),
      );
    } catch (err) {
      setSearchError(err);
    } finally {
      setSearching(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title="검색 시험"
        description="질문하면 어떤 내용이 찾아지는지 미리 볼 수 있어요."
      />
      <CardBody className="space-y-3">
        <form onSubmit={search} className="space-y-2">
          <div className="flex gap-2">
            <Input
              aria-label="검색어"
              placeholder="예: 연차는 며칠인가요?"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <Button type="submit" disabled={searching}>
              <Search className="h-4 w-4" /> 검색
            </Button>
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            <Select
              aria-label="검색 방식"
              value={method}
              onChange={(e) => setMethod(e.target.value as RetrievalMethod)}
            >
              <option value="vector">의미(벡터)</option>
              <option value="keyword">낱말(키워드)</option>
              <option value="hybrid">둘 다(혼합)</option>
            </Select>
            <Input
              type="number"
              step={0.05}
              min={0}
              max={1}
              aria-label="점수 기준"
              placeholder="점수 기준(0~1)"
              value={threshold}
              onChange={(e) => setThreshold(Math.max(0, Math.min(1, Number(e.target.value) || 0)))}
            />
            <Input
              aria-label="꼬리표로 거르기"
              placeholder="꼬리표 거르기(예: 부서=인사)"
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
            />
          </div>
        </form>
        <ErrorBox error={searchError} />
        {hits?.length === 0 && <p className="text-sm text-slate-500">찾은 내용이 없어요.</p>}
        {hits?.map((h) => (
          <div key={h.chunk_id} className="rounded-xl border border-slate-200 p-3 text-sm">
            <div className="mb-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
              <span>{h.filename}</span>
              <span>· 점수 {h.score.toFixed(3)}</span>
              {Object.entries(h.metadata ?? {}).map(([k, v]) => (
                <Badge key={k} tone="blue">
                  {k}={v}
                </Badge>
              ))}
            </div>
            <p className="whitespace-pre-wrap">{h.content}</p>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

function KbDetail({ ws, kb, editable }: { ws: string; kb: KnowledgeBaseV2; editable: boolean }) {
  const docs = useDocuments(kb.id);
  const upload = useUploadDocument(kb.id);
  const delDoc = useDeleteDocument(kb.id);
  const reprocess = useReprocessDocument(kb.id);
  const fileRef = useRef<HTMLInputElement>(null);
  const settings = normalizeKbSettings(kb.settings);
  const [dialog, setDialog] = useState<"settings" | "url" | null>(null);
  const [metaDoc, setMetaDoc] = useState<KbDocumentV2 | null>(null);
  const [chunkDoc, setChunkDoc] = useState<KbDocumentV2 | null>(null);
  const docList = (docs.data ?? []) as KbDocumentV2[];

  return (
    <div className="min-w-0 space-y-6">
      <Card>
        <CardHeader
          title={kb.name}
          description={`${settings.chunk_mode === "parent_child" ? "부모-자식" : "일반"} 조각 ${settings.chunk_size}자 · ${METHOD_LABEL[settings.retrieval.method]} 검색 · 임베딩 ${kb.embedding_model}`}
          action={
            editable && (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => setDialog("settings")}>
                  <Settings2 className="h-3.5 w-3.5" /> 설정
                </Button>
                <Button size="sm" variant="outline" onClick={() => setDialog("url")}>
                  <Globe className="h-3.5 w-3.5" /> 웹 페이지
                </Button>
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
                  <Upload className="h-3.5 w-3.5" />
                  {upload.isPending ? "올리는 중…" : "문서 올리기"}
                </Button>
              </div>
            )
          }
        />
        <CardBody className="p-0">
          {docs.isLoading && <Loading />}
          <ErrorBox error={docs.error} />
          {docs.data?.length === 0 && (
            <p className="px-5 py-6 text-sm text-slate-500">
              PDF, TXT, MD 파일을 올리거나 웹 페이지를 가져오면 질문에 답할 때 써요.
            </p>
          )}
          <ul className="divide-y divide-slate-100 border-t border-slate-100">
            {docList.map((d) => (
              <DocRow
                key={d.id}
                d={d}
                editable={editable}
                reprocessing={reprocess.isPending}
                onChunks={() => setChunkDoc(d)}
                onMeta={() => setMetaDoc(d)}
                onReprocess={() =>
                  reprocess.mutate(d.id, {
                    onSuccess: () => toast.success("다시 나누는 중이에요."),
                    onError: (err) => toast.error(err),
                  })
                }
                onDelete={() => {
                  if (window.confirm(`'${d.filename}'을(를) 지울까요?`)) delDoc.mutate(d.id);
                }}
              />
            ))}
          </ul>
        </CardBody>
      </Card>
      {editable && <SearchCard key={kb.id} kb={kb} />}
      {dialog === "settings" && (
        <KbSettingsDialog ws={ws} kb={kb} open onClose={() => setDialog(null)} />
      )}
      {dialog === "url" && <UrlImportDialog kbId={kb.id} open onClose={() => setDialog(null)} />}
      {metaDoc && <MetadataDialog kbId={kb.id} doc={metaDoc} onClose={() => setMetaDoc(null)} />}
      {chunkDoc && (
        <ChunksDialog doc={chunkDoc} editable={editable} onClose={() => setChunkDoc(null)} />
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

  const kb = (kbs.data ?? []).find((k) => k.id === selected) as KnowledgeBaseV2 | undefined;

  return (
    <PageContainer>
      <PageHeader
        title="지식베이스"
        description="문서를 올려 두면 챗봇이 그 내용으로 답해요."
        help={<HelpButton page="knowledge" />}
      />
      <ErrorBox error={kbs.error} />
      <div className="grid gap-6 md:grid-cols-[240px_1fr]">
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
                <div className="flex gap-2">
                  <Input
                    id="kb-name"
                    placeholder="예: 사내 규정"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                  <Button type="submit" disabled={create.isPending || !name.trim()}>
                    만들기
                  </Button>
                </div>
              </Field>
              <ErrorBox error={create.error} />
            </form>
          )}
          {kbs.isLoading && <Loading />}
          <ul className="flex gap-1 overflow-x-auto pb-1 md:block md:space-y-1 md:overflow-visible">
            {(kbs.data ?? []).map((k) => (
              <li key={k.id} className="group flex shrink-0 items-center">
                <button
                  type="button"
                  onClick={() => setSelected(k.id)}
                  className={cn(
                    "flex-1 rounded-lg px-3 py-2 text-left text-sm",
                    k.id === selected
                      ? "bg-indigo-50 font-medium text-indigo-700"
                      : "hover:bg-slate-100",
                  )}
                >
                  {k.name}
                  <span className="ml-1 text-xs text-slate-400">({k.document_count})</span>
                  <span className="hidden text-[11px] text-slate-400 md:block">
                    {formatDate(k.created_at)}
                  </span>
                </button>
                {editable && (
                  <button
                    type="button"
                    aria-label={`${k.name} 삭제`}
                    className="hidden px-2 text-xs text-red-500 group-hover:block md:invisible md:block md:group-hover:visible"
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
        <div className="min-w-0">
          {kb ? (
            <KbDetail key={kb.id} ws={ws} kb={kb} editable={editable} />
          ) : (
            kbs.data && <Empty>지식베이스를 만들고 문서를 올려 보세요.</Empty>
          )}
        </div>
      </div>
    </PageContainer>
  );
}
