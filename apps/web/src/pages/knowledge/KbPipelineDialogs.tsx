// v0.6 문서 처리 순서 편집·미리 보기, 질문·답 표 가져오기
import { Eye, FileUp, Plus, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import type {
  KbDocumentV2,
  KbSettings,
  KnowledgeBaseV2,
  PipelinePreview,
  PipelineStep,
  QaColumns,
} from "@/lib/api/types";
import { normalizeKbSettings } from "@/lib/api/types";
import { useUpdateKnowledgeBase } from "@/lib/api/v2";
import { useImportQa, usePreviewPipeline, useQaColumns, useReprocessKb } from "@/lib/api/v6kb";
import { cn } from "@/lib/cn";
import {
  STEP_INFO,
  formatPairs,
  normalizePipeline,
  parsePairs,
} from "@/pages/knowledge/pipelineSteps";

const MODE_LABEL: Record<KbSettings["chunk_mode"], string> = {
  general: "일반",
  parent_child: "부모-자식",
  qa: "질문·답",
};

function Check({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-slate-700">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function StepSettings({
  step,
  onChange,
  mode,
}: {
  step: PipelineStep;
  onChange: (s: PipelineStep) => void;
  mode: KbSettings["chunk_mode"];
}) {
  if (step.type === "clean") {
    const pats = step.remove_patterns ?? [];
    return (
      <div className="space-y-2">
        <div className="grid gap-1.5 sm:grid-cols-2">
          <Check
            label="빈칸·빈 줄 줄이기"
            checked={step.collapse_spaces ?? true}
            onChange={(v) => onChange({ ...step, collapse_spaces: v })}
          />
          <Check
            label="쪽마다 되풀이되는 머리글·바닥글 지우기"
            checked={step.remove_repeated_lines ?? false}
            onChange={(v) => onChange({ ...step, remove_repeated_lines: v })}
          />
          <Check
            label="웹 주소를 [주소]로 가리기"
            checked={step.mask_urls ?? false}
            onChange={(v) => onChange({ ...step, mask_urls: v })}
          />
          <Check
            label="이메일을 [이메일]로 가리기"
            checked={step.mask_emails ?? false}
            onChange={(v) => onChange({ ...step, mask_emails: v })}
          />
        </div>
        <p className="text-xs font-medium text-slate-600">지울 글 패턴(고급, 정규식)</p>
        {pats.map((p, i) => (
          <div key={i} className="flex gap-2">
            <Input
              aria-label={`지울 글 패턴 ${i + 1}`}
              className="font-mono text-xs"
              value={p}
              placeholder="예: 대외비\s*-\s*\d+쪽"
              onChange={(e) =>
                onChange({
                  ...step,
                  remove_patterns: pats.map((x, j) => (j === i ? e.target.value : x)),
                })
              }
            />
            <Button
              size="sm"
              variant="ghost"
              className="h-10 text-slate-400"
              aria-label="패턴 지우기"
              onClick={() => onChange({ ...step, remove_patterns: pats.filter((_, j) => j !== i) })}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}
        {pats.length < 10 && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onChange({ ...step, remove_patterns: [...pats, ""] })}
          >
            <Plus className="h-3.5 w-3.5" /> 패턴 추가
          </Button>
        )}
      </div>
    );
  }
  if (step.type === "metadata") {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="모든 문서에 붙일 꼬리표" htmlFor="pl-fixed" hint="예: 출처=사내, 연도=2026">
          <Input
            id="pl-fixed"
            defaultValue={formatPairs(step.fixed)}
            onBlur={(e) => onChange({ ...step, fixed: parsePairs(e.target.value) })}
          />
        </Field>
        <Field
          label="파일 이름에서 뽑기(고급)"
          htmlFor="pl-fname"
          hint="예: (?P<부서>[^_]+)_(?P<연도>\d{4}) → 인사_2026.pdf"
        >
          <Input
            id="pl-fname"
            className="font-mono text-xs"
            value={step.filename_pattern ?? ""}
            onChange={(e) => onChange({ ...step, filename_pattern: e.target.value })}
          />
        </Field>
      </div>
    );
  }
  if (step.type === "split") {
    return (
      <p className="text-xs text-slate-500">
        지금 방식: <b>{MODE_LABEL[mode]}</b> (지식베이스 &gt; 설정에서 바꿔요)
      </p>
    );
  }
  return null;
}

function PreviewPanel({ data }: { data: PipelinePreview }) {
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <Badge tone="indigo">조각 {data.total}개</Badge>
        <span>{MODE_LABEL[data.chunk_mode]} 방식</span>
        {Object.entries(data.metadata).map(([k, v]) => (
          <Badge key={k}>
            {k}={v}
          </Badge>
        ))}
      </div>
      <ul className="list-disc pl-4 text-xs text-slate-600">
        {data.log.map((l, i) => (
          <li key={i}>{l}</li>
        ))}
      </ul>
      <div className="max-h-80 space-y-2 overflow-y-auto pr-1">
        {data.chunks.map((c) => (
          <div key={c.index} className="rounded-lg border border-slate-200 p-2.5 text-xs">
            <p className="mb-1 text-slate-400">
              #{c.index + 1} · {c.char_count}자
            </p>
            {c.question !== undefined ? (
              <>
                <p className="font-medium text-slate-800">질문: {c.question}</p>
                <p className="whitespace-pre-wrap text-slate-600">답: {c.answer}</p>
              </>
            ) : (
              <p className="whitespace-pre-wrap text-slate-700">{c.content}</p>
            )}
          </div>
        ))}
        {data.total > data.chunks.length && (
          <p className="text-xs text-slate-400">앞의 {data.chunks.length}개만 보여 줘요.</p>
        )}
      </div>
    </div>
  );
}

export function PipelineDialog({
  ws,
  kb,
  docs,
  onClose,
}: {
  ws: string;
  kb: KnowledgeBaseV2;
  docs: KbDocumentV2[];
  onClose: () => void;
}) {
  const base = normalizeKbSettings(kb.settings);
  const [steps, setSteps] = useState<PipelineStep[]>(() => normalizePipeline(base.pipeline));
  const update = useUpdateKnowledgeBase(ws);
  const reprocess = useReprocessKb(kb.id);
  const preview = usePreviewPipeline(kb.id);
  const [docId, setDocId] = useState(docs[0]?.id ?? "");
  const fileRef = useRef<HTMLInputElement>(null);
  const setStep = (s: PipelineStep) => setSteps(steps.map((x) => (x.type === s.type ? s : x)));
  const run = (file?: File) =>
    preview.mutate({ file, documentId: file ? undefined : docId, settings: { pipeline: steps } });

  const save = (again: boolean) =>
    update.mutate(
      { id: kb.id, settings: { pipeline: steps } },
      {
        onSuccess: () => {
          if (!again) {
            toast.success("처리 순서를 저장했어요. 새로 올리는 문서부터 반영돼요.");
            onClose();
            return;
          }
          reprocess.mutate(undefined, {
            onSuccess: (r) => {
              toast.success(`저장하고 문서 ${r.queued}개를 다시 나누는 중이에요.`);
              onClose();
            },
          });
        },
      },
    );

  return (
    <Dialog
      open
      onClose={onClose}
      title="문서 처리 순서"
      wide
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            취소
          </Button>
          <Button
            variant="outline"
            disabled={update.isPending || reprocess.isPending || docs.length === 0}
            onClick={() => save(true)}
          >
            저장하고 모든 문서 다시 나누기
          </Button>
          <Button disabled={update.isPending} onClick={() => save(false)}>
            저장
          </Button>
        </>
      }
    >
      <div className="grid gap-5 text-sm lg:grid-cols-2">
        <ol className="space-y-2">
          {steps.map((s) => {
            const info = STEP_INFO[s.type];
            return (
              <li
                key={s.type}
                className={cn(
                  "rounded-xl border p-3",
                  s.enabled ? "border-indigo-200 bg-indigo-50/30" : "border-slate-200",
                )}
              >
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-slate-900">{info.label}</p>
                    <p className="text-xs text-slate-500">{info.desc}</p>
                  </div>
                  {info.always ? (
                    <Badge>항상</Badge>
                  ) : (
                    <label className="flex shrink-0 items-center gap-1.5 text-xs">
                      <input
                        type="checkbox"
                        aria-label={`${info.label} 켜기`}
                        checked={s.enabled}
                        onChange={(e) => setStep({ ...s, enabled: e.target.checked })}
                      />
                      켜기
                    </label>
                  )}
                </div>
                {(s.enabled || s.type === "split") && (
                  <div className="mt-2">
                    <StepSettings step={s} onChange={setStep} mode={base.chunk_mode} />
                  </div>
                )}
              </li>
            );
          })}
        </ol>
        <div className="space-y-3">
          <p className="font-semibold text-slate-800">미리 보기</p>
          <p className="text-xs text-slate-500">
            저장하지 않고 지금 순서로 나눠 봐요. 질문·답 방식은 앞의 몇 조각만 AI로 만들어 봐요.
          </p>
          <div className="flex flex-wrap gap-2">
            {docs.length > 0 && (
              <>
                <Select
                  aria-label="미리 볼 문서"
                  className="max-w-[14rem]"
                  value={docId}
                  onChange={(e) => setDocId(e.target.value)}
                >
                  {docs.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.filename}
                    </option>
                  ))}
                </Select>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={preview.isPending || !docId}
                  onClick={() => run()}
                >
                  <Eye className="h-3.5 w-3.5" /> 이 문서로 미리 보기
                </Button>
              </>
            )}
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              aria-label="미리 볼 파일"
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) run(f);
              }}
            />
            <Button
              size="sm"
              variant="outline"
              disabled={preview.isPending}
              onClick={() => fileRef.current?.click()}
            >
              <FileUp className="h-3.5 w-3.5" /> 파일로 미리 보기
            </Button>
          </div>
          {preview.isPending && <p className="text-xs text-slate-500">나눠 보는 중…</p>}
          <ErrorBox error={preview.error ?? update.error ?? reprocess.error} />
          {preview.data && <PreviewPanel data={preview.data} />}
        </div>
      </div>
    </Dialog>
  );
}

export function QaImportDialog({ kbId, onClose }: { kbId: string; onClose: () => void }) {
  const columns = useQaColumns(kbId);
  const imp = useImportQa(kbId);
  const [file, setFile] = useState<File | null>(null);
  const [cols, setCols] = useState<QaColumns | null>(null);
  const [q, setQ] = useState("");
  const [a, setA] = useState("");
  return (
    <Dialog
      open
      onClose={onClose}
      title="질문·답 표 가져오기"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            취소
          </Button>
          <Button
            disabled={!file || !q || !a || q === a || imp.isPending}
            onClick={() =>
              file &&
              imp.mutate(
                { file, question_column: q, answer_column: a },
                {
                  onSuccess: (d) => {
                    toast.success(
                      d.status === "ready"
                        ? `질문·답 ${d.chunk_count}개를 넣었어요.`
                        : "가져오는 중이에요. 처리가 끝나면 '준비됨'으로 바뀌어요.",
                    );
                    onClose();
                  },
                },
              )
            }
          >
            가져오기
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <p className="text-xs text-slate-500">
          자주 묻는 질문을 엑셀(XLSX)이나 CSV로 올리면 한 줄이 조각 하나가 돼요. 질문으로 찾고, 답을
          그대로 돌려줘요.
        </p>
        <Field label="표 파일" htmlFor="qa-file" hint="첫 줄은 열 이름(예: 질문, 답)">
          <Input
            id="qa-file"
            type="file"
            accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              setCols(null);
              if (!f) return;
              columns.mutate(f, {
                onSuccess: (c) => {
                  setCols(c);
                  setQ(c.question_column ?? c.columns[0] ?? "");
                  setA(c.answer_column ?? c.columns[1] ?? "");
                },
              });
            }}
          />
        </Field>
        {cols && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Field label="질문 열" htmlFor="qa-q">
                <Select id="qa-q" value={q} onChange={(e) => setQ(e.target.value)}>
                  {cols.columns.map((c) => (
                    <option key={c} value={c}>
                      {c || "(이름 없음)"}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="답 열" htmlFor="qa-a">
                <Select id="qa-a" value={a} onChange={(e) => setA(e.target.value)}>
                  {cols.columns.map((c) => (
                    <option key={c} value={c}>
                      {c || "(이름 없음)"}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            {q === a && (
              <p className="text-xs text-red-600">질문 열과 답 열을 다르게 골라 주세요.</p>
            )}
            <p className="text-xs text-slate-500">모두 {cols.row_count}줄 · 앞의 몇 줄:</p>
            <ul className="space-y-1 text-xs">
              {cols.sample.map((row, i) => {
                const qi = cols.columns.indexOf(q);
                const ai = cols.columns.indexOf(a);
                return (
                  <li key={i} className="rounded-lg bg-slate-50 px-2.5 py-1.5">
                    <b>질문</b> {row[qi] ?? ""} · <b>답</b> {row[ai] ?? ""}
                  </li>
                );
              })}
            </ul>
          </>
        )}
        <ErrorBox error={columns.error ?? imp.error} />
      </div>
    </Dialog>
  );
}
