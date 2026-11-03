import { Eye, EyeOff, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import type { KbDocumentV2, KbSettings, KnowledgeBaseV2 } from "@/lib/api/types";
import { normalizeKbSettings } from "@/lib/api/types";
import {
  useChunks,
  useImportUrl,
  useUpdateChunk,
  useUpdateDocument,
  useUpdateKnowledgeBase,
} from "@/lib/api/v2";
import { useProjects } from "@/lib/api/v3";
import { cn } from "@/lib/cn";
import { useListControls } from "@/lib/useListControls";

export function KbSettingsDialog({
  ws,
  kb,
  open,
  onClose,
}: {
  ws: string;
  kb: KnowledgeBaseV2;
  open: boolean;
  onClose: () => void;
}) {
  const update = useUpdateKnowledgeBase(ws);
  const [name, setName] = useState(kb.name);
  const [projectId, setProjectId] = useState(kb.project_id ?? "");
  const projects = useProjects(open ? ws : "");
  const [s, setS] = useState<KbSettings>(() => normalizeKbSettings(kb.settings));
  const r = s.retrieval;
  const num = (v: string, min: number, max: number, fallback: number) =>
    Math.max(min, Math.min(max, Number(v) || fallback));

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="지식베이스 설정"
      wide
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            취소
          </Button>
          <Button
            disabled={update.isPending || !name.trim()}
            onClick={() =>
              update.mutate(
                { id: kb.id, name, settings: s, project_id: projectId },
                {
                  onSuccess: () => {
                    toast.success(
                      "설정을 저장했어요. 문서별 '다시 나누기'를 누르면 새 설정이 반영돼요.",
                    );
                    onClose();
                  },
                },
              )
            }
          >
            저장
          </Button>
        </>
      }
    >
      <div className="space-y-5 text-sm">
        <Field label="이름" htmlFor="kb-set-name">
          <Input id="kb-set-name" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="프로젝트" htmlFor="kb-set-project">
          <Select
            id="kb-set-project"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
          >
            <option value="">프로젝트 없음</option>
            {(projects.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
        <fieldset className="space-y-3">
          <legend className="mb-2 text-sm font-semibold text-slate-800">조각 나누기</legend>
          <div className="grid gap-2 sm:grid-cols-3">
            {(
              [
                ["general", "일반", "정한 길이로 잘라요."],
                [
                  "parent_child",
                  "부모-자식",
                  "작은 조각으로 찾고, 그 조각이 든 큰 문단을 돌려줘요.",
                ],
                [
                  "qa",
                  "질문·답",
                  "AI가 문서로 질문·답을 만들어 질문으로 찾아요(AI 키 필요). 표는 '질문·답 표'로 가져와요.",
                ],
              ] as const
            ).map(([v, label, desc]) => (
              <label
                key={v}
                className={cn(
                  "flex cursor-pointer gap-2 rounded-xl border p-3",
                  s.chunk_mode === v ? "border-indigo-400 bg-indigo-50/50" : "border-slate-200",
                )}
              >
                <input
                  type="radio"
                  name="chunk-mode"
                  checked={s.chunk_mode === v}
                  onChange={() => setS({ ...s, chunk_mode: v })}
                />
                <span>
                  <span className="block font-medium">{label}</span>
                  <span className="block text-xs text-slate-500">{desc}</span>
                </span>
              </label>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Field label="구분자" htmlFor="kb-sep" hint="\n = 줄바꿈">
              <Input
                id="kb-sep"
                className="font-mono text-xs"
                value={s.separator.replace(/\n/g, "\\n")}
                onChange={(e) => setS({ ...s, separator: e.target.value.replace(/\\n/g, "\n") })}
              />
            </Field>
            <Field
              label={s.chunk_mode === "parent_child" ? "부모 크기" : "조각 크기"}
              htmlFor="kb-size"
            >
              <Input
                id="kb-size"
                type="number"
                value={s.chunk_size}
                onChange={(e) => setS({ ...s, chunk_size: num(e.target.value, 100, 4000, 800) })}
              />
            </Field>
            <Field label="겹침" htmlFor="kb-overlap">
              <Input
                id="kb-overlap"
                type="number"
                value={s.chunk_overlap}
                onChange={(e) => setS({ ...s, chunk_overlap: num(e.target.value, 0, 1000, 0) })}
              />
            </Field>
            {s.chunk_mode === "qa" && (
              <Field label="조각마다 질문·답" htmlFor="kb-qa-n" hint="1~10쌍">
                <Input
                  id="kb-qa-n"
                  type="number"
                  value={s.qa_pairs_per_chunk}
                  onChange={(e) =>
                    setS({ ...s, qa_pairs_per_chunk: num(e.target.value, 1, 10, 3) })
                  }
                />
              </Field>
            )}
            {s.chunk_mode === "parent_child" && (
              <Field label="자식 크기" htmlFor="kb-child">
                <Input
                  id="kb-child"
                  type="number"
                  value={s.child_chunk_size}
                  onChange={(e) =>
                    setS({ ...s, child_chunk_size: num(e.target.value, 50, 2000, 200) })
                  }
                />
              </Field>
            )}
          </div>
        </fieldset>
        <fieldset className="space-y-3">
          <legend className="mb-2 text-sm font-semibold text-slate-800">검색</legend>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Field label="검색 방식" htmlFor="kb-method">
              <Select
                id="kb-method"
                value={r.method}
                onChange={(e) =>
                  setS({
                    ...s,
                    retrieval: {
                      ...r,
                      method: e.target.value as KbSettings["retrieval"]["method"],
                    },
                  })
                }
              >
                <option value="vector">의미(벡터)</option>
                <option value="keyword">낱말(키워드)</option>
                <option value="hybrid">둘 다(혼합)</option>
              </Select>
            </Field>
            <Field label="가져올 개수" htmlFor="kb-topk">
              <Input
                id="kb-topk"
                type="number"
                value={r.top_k}
                onChange={(e) =>
                  setS({ ...s, retrieval: { ...r, top_k: num(e.target.value, 1, 20, 4) } })
                }
              />
            </Field>
            <Field label="점수 기준(0~1)" htmlFor="kb-score">
              <Input
                id="kb-score"
                type="number"
                step={0.05}
                value={r.score_threshold}
                onChange={(e) =>
                  setS({ ...s, retrieval: { ...r, score_threshold: num(e.target.value, 0, 1, 0) } })
                }
              />
            </Field>
          </div>
          {r.method === "hybrid" && (
            <label className="block space-y-1 text-xs">
              <span className="font-medium text-slate-600">
                의미 비중 {Math.round(r.vector_weight * 100)}% · 낱말 비중{" "}
                {Math.round((1 - r.vector_weight) * 100)}%
              </span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                aria-label="의미 비중"
                className="w-full accent-indigo-600"
                value={r.vector_weight}
                onChange={(e) =>
                  setS({ ...s, retrieval: { ...r, vector_weight: Number(e.target.value) } })
                }
              />
            </label>
          )}
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={r.rerank}
              onChange={(e) => setS({ ...s, retrieval: { ...r, rerank: e.target.checked } })}
            />
            AI로 다시 순위 매기기(정확해지지만 느리고 비용이 들어요)
          </label>
        </fieldset>
        <ErrorBox error={update.error} />
      </div>
    </Dialog>
  );
}

export function UrlImportDialog({
  kbId,
  open,
  onClose,
}: {
  kbId: string;
  open: boolean;
  onClose: () => void;
}) {
  const imp = useImportUrl(kbId);
  const [url, setUrl] = useState("");
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="웹 페이지 가져오기"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            취소
          </Button>
          <Button
            disabled={imp.isPending || !/^https?:\/\//.test(url.trim())}
            onClick={() =>
              imp.mutate(url.trim(), {
                onSuccess: () => {
                  toast.success("가져오는 중이에요. 처리가 끝나면 '준비됨'으로 바뀌어요.");
                  setUrl("");
                  onClose();
                },
              })
            }
          >
            가져오기
          </Button>
        </>
      }
    >
      <div className="space-y-2 text-sm">
        <Field
          label="주소"
          htmlFor="kb-url"
          hint="공개된 페이지 하나의 글을 가져와요. 사내망 주소는 막혀 있어요."
        >
          <Input
            id="kb-url"
            type="url"
            placeholder="https://example.com/faq"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </Field>
        <ErrorBox error={imp.error} />
      </div>
    </Dialog>
  );
}

export function MetadataDialog({
  kbId,
  doc,
  onClose,
}: {
  kbId: string;
  doc: KbDocumentV2;
  onClose: () => void;
}) {
  const update = useUpdateDocument(kbId);
  const [rows, setRows] = useState<[string, string][]>(() =>
    Object.entries(doc.metadata ?? {}).map(([k, v]) => [k, String(v)]),
  );
  return (
    <Dialog
      open
      onClose={onClose}
      title={`꼬리표 · ${doc.filename}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            취소
          </Button>
          <Button
            disabled={update.isPending}
            onClick={() =>
              update.mutate(
                {
                  id: doc.id,
                  metadata: Object.fromEntries(
                    rows.filter(([k]) => k.trim()).map(([k, v]) => [k.trim(), v]),
                  ),
                },
                {
                  onSuccess: () => {
                    toast.success("꼬리표를 저장했어요.");
                    onClose();
                  },
                },
              )
            }
          >
            저장
          </Button>
        </>
      }
    >
      <div className="space-y-2 text-sm">
        <p className="text-xs text-slate-500">
          예: 부서=인사, 연도=2026. 검색이나 지식 검색 단계에서 꼬리표로 거를 수 있어요.
        </p>
        {rows.map(([k, v], i) => (
          <div key={i} className="flex gap-2">
            <Input
              aria-label={`꼬리표 이름 ${i + 1}`}
              placeholder="이름"
              value={k}
              onChange={(e) => setRows(rows.map((r, j) => (j === i ? [e.target.value, r[1]] : r)))}
            />
            <Input
              aria-label={`꼬리표 값 ${i + 1}`}
              placeholder="값"
              value={v}
              onChange={(e) => setRows(rows.map((r, j) => (j === i ? [r[0], e.target.value] : r)))}
            />
            <Button
              variant="ghost"
              size="sm"
              className="h-10 text-slate-400"
              aria-label="꼬리표 지우기"
              onClick={() => setRows(rows.filter((_, j) => j !== i))}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}
        <Button size="sm" variant="outline" onClick={() => setRows([...rows, ["", ""]])}>
          <Plus className="h-3.5 w-3.5" /> 꼬리표 추가
        </Button>
        <ErrorBox error={update.error} />
      </div>
    </Dialog>
  );
}

export function ChunksDialog({
  doc,
  onClose,
  editable,
}: {
  doc: KbDocumentV2;
  onClose: () => void;
  editable: boolean;
}) {
  const chunks = useChunks(doc.id);
  const update = useUpdateChunk(doc.id);
  const [editing, setEditing] = useState<{ id: string; content: string } | null>(null);
  const cc = useListControls(chunks.data, {
    key: "kb-chunks",
    defaultSize: 10,
    search: (c) => `${c.content} ${c.parent_content ?? ""}`,
    filters: [
      {
        id: "enabled",
        label: "검색 사용",
        options: [
          { value: "on", label: "검색에 씀" },
          { value: "off", label: "검색에서 뺌" },
        ],
        match: (c, v) => c.enabled === (v === "on"),
      },
    ],
  });
  return (
    <Dialog open onClose={onClose} title={`조각 보기 · ${doc.filename}`} wide>
      <div className="space-y-2">
        {chunks.isLoading && <Loading />}
        <ErrorBox error={chunks.error ?? update.error} />
        {chunks.data?.length === 0 && <p className="text-sm text-slate-500">조각이 없어요.</p>}
        {(chunks.data ?? []).length > 0 && <ListToolbar c={cc} placeholder="조각 내용으로 찾기" />}
        <NoMatch c={cc} />
        {cc.pageItems.map((c) => (
          <div
            key={c.id}
            className={cn(
              "rounded-xl border p-3 text-sm",
              c.enabled
                ? "border-slate-200"
                : "border-dashed border-slate-300 bg-slate-50 opacity-70",
            )}
          >
            <div className="mb-1.5 flex flex-wrap items-center gap-2 text-xs text-slate-400">
              <Badge tone="indigo">#{c.index + 1}</Badge>
              <span>{c.char_count}자</span>
              {!c.enabled && <Badge>검색에서 뺌</Badge>}
              {editable && (
                <span className="ml-auto flex gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="조각 고치기"
                    onClick={() => setEditing({ id: c.id, content: c.content })}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={c.enabled ? "검색에서 빼기" : "검색에 다시 넣기"}
                    onClick={() => update.mutate({ id: c.id, enabled: !c.enabled })}
                  >
                    {c.enabled ? (
                      <EyeOff className="h-3.5 w-3.5" />
                    ) : (
                      <Eye className="h-3.5 w-3.5" />
                    )}
                  </Button>
                </span>
              )}
            </div>
            {editing?.id === c.id ? (
              <div className="space-y-2">
                <Textarea
                  aria-label="조각 내용"
                  className="min-h-[140px]"
                  value={editing.content}
                  onChange={(e) => setEditing({ id: c.id, content: e.target.value })}
                />
                <div className="flex justify-end gap-2">
                  <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
                    취소
                  </Button>
                  <Button
                    size="sm"
                    disabled={update.isPending}
                    onClick={() =>
                      update.mutate(
                        { id: c.id, content: editing.content },
                        { onSuccess: () => setEditing(null) },
                      )
                    }
                  >
                    저장
                  </Button>
                </div>
              </div>
            ) : (
              <p className="whitespace-pre-wrap text-slate-700">{c.content}</p>
            )}
            {c.parent_content && editing?.id !== c.id && (
              <details className="mt-2 text-xs text-slate-500">
                <summary className="cursor-pointer">부모 문단 보기</summary>
                <p className="mt-1 whitespace-pre-wrap rounded-lg bg-slate-50 p-2">
                  {c.parent_content}
                </p>
              </details>
            )}
          </div>
        ))}
        {(chunks.data ?? []).length > 0 && <ListPager c={cc} className="pt-1" />}
      </div>
    </Dialog>
  );
}
