// 일괄 실행: 양식 내려받기 → 표 올리기(미리 보기·오류 확인) → 실행 → 진행·결과 → 결과 표 내려받기.
import { Download, FileSpreadsheet, Loader2, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast-store";
import {
  BATCH_STATUS_LABEL,
  downloadBatchFile,
  useBatchStatus,
  useCancelBatch,
  useCreateBatch,
  usePreviewBatch,
  type BatchPreview,
  type BatchRowStatus,
  type BatchSource,
} from "@/lib/api/batches";
import { progressOf } from "@/lib/batchProgress";
import { cn } from "@/lib/cn";

const PREVIEW_ROWS = 10;
const RESULT_ROWS = 50;

const STATUS_TONE: Record<BatchRowStatus, string> = {
  queued: "bg-slate-100 text-slate-600",
  running: "bg-indigo-50 text-indigo-700",
  succeeded: "bg-emerald-50 text-emerald-700",
  failed: "bg-red-50 text-red-700",
  cancelled: "bg-slate-100 text-slate-500",
  waiting_approval: "bg-amber-50 text-amber-700",
};

function show(v: unknown): string {
  if (v === null || v === undefined) return "";
  return typeof v === "string" ? v : JSON.stringify(v);
}

function clip(text: string, n: number): string {
  return text.length > n ? `${text.slice(0, n)}…` : text;
}

export function BatchRunPanel({ source, note }: { source: BatchSource; note?: string }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const preview = usePreviewBatch(source);
  const create = useCreateBatch(source);
  const cancel = useCancelBatch(source);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [showAllResults, setShowAllResults] = useState(false);
  const status = useBatchStatus(source, batchId);
  const data: BatchPreview | undefined = preview.data;

  const download = async (kind: "template" | "results") => {
    try {
      await downloadBatchFile(source, kind, batchId ?? undefined);
    } catch (err) {
      toast.error(err);
    }
  };

  const run = (skipInvalid: boolean) => {
    if (!data) return;
    const rows = data.rows
      .filter((r) => !skipInvalid || r.errors.length === 0)
      .map((r) => ({ row: r.row, values: r.values }));
    create.mutate(
      { rows, skipInvalid },
      {
        onSuccess: (r) => {
          setBatchId(r.batch_id);
          setShowAllResults(false);
        },
      },
    );
  };

  const reset = () => {
    setBatchId(null);
    preview.reset();
    create.reset();
    if (fileRef.current) fileRef.current.value = "";
  };

  // ---------- 실행 중·끝난 화면 ----------
  if (batchId) {
    const st = status.data;
    const prog = st ? progressOf(st.counts, st.total) : null;
    const rows = st?.rows ?? [];
    const shown = showAllResults ? rows : rows.slice(0, RESULT_ROWS);
    return (
      <div className="space-y-3" data-testid="batch-running">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-semibold text-slate-900">
            {st?.done ? (st.cancelled ? "취소했어요" : "끝났어요") : "실행하는 중…"}
          </p>
          {prog && (
            <span className="text-xs text-slate-500">
              {prog.settled}/{prog.total}줄 · {prog.summary}
            </span>
          )}
        </div>
        <div
          role="progressbar"
          aria-label="일괄 실행 진행"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={prog?.percent ?? 0}
          className="h-2 overflow-hidden rounded-full bg-slate-100"
        >
          <div
            className="h-full rounded-full bg-indigo-600 transition-all"
            style={{ width: `${prog?.percent ?? 0}%` }}
          />
        </div>
        <ErrorBox error={status.error} />
        <div className="flex flex-wrap gap-2">
          {st && !st.done && (
            <Button
              size="sm"
              variant="outline"
              disabled={cancel.isPending}
              onClick={() =>
                cancel.mutate(batchId, {
                  onSuccess: (r) =>
                    toast.info(
                      r.cancelled > 0
                        ? `아직 시작하지 않은 ${r.cancelled}줄을 취소했어요. 이미 도는 줄은 끝까지 가요.`
                        : "취소할 줄이 없어요. 이미 모두 시작했어요.",
                    ),
                  onError: (err) => toast.error(err),
                })
              }
            >
              <X className="h-3.5 w-3.5" /> 취소
            </Button>
          )}
          <Button
            size="sm"
            variant={st?.done ? "primary" : "outline"}
            disabled={!st || st.settled === 0}
            onClick={() => void download("results")}
          >
            <Download className="h-3.5 w-3.5" /> 결과 표 내려받기
          </Button>
          {st?.done && (
            <Button size="sm" variant="ghost" onClick={reset}>
              새로 하기
            </Button>
          )}
        </div>
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full min-w-[420px] text-left text-xs">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="w-12 px-2 py-1.5 font-medium">줄</th>
                <th className="w-20 px-2 py-1.5 font-medium">상태</th>
                <th className="px-2 py-1.5 font-medium">결과</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {shown.map((r) => (
                <tr key={r.row}>
                  <td className="px-2 py-1.5 text-slate-500">{r.row}</td>
                  <td className="px-2 py-1.5">
                    <span
                      className={cn(
                        "inline-block rounded px-1.5 py-0.5 text-[11px] font-medium",
                        STATUS_TONE[r.status],
                      )}
                    >
                      {BATCH_STATUS_LABEL[r.status]}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-slate-800">
                    {r.error ? (
                      <span className="text-red-700">
                        {r.error.message} {r.error.hint}
                      </span>
                    ) : (
                      <span className="whitespace-pre-wrap">{clip(r.text, 160)}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rows.length > RESULT_ROWS && !showAllResults && (
          <button
            type="button"
            className="text-xs font-medium text-indigo-600 hover:underline"
            onClick={() => setShowAllResults(true)}
          >
            {rows.length - RESULT_ROWS}줄 더 보기(전체는 결과 표로 받아요)
          </button>
        )}
      </div>
    );
  }

  // ---------- 올리기·미리 보기 화면 ----------
  const fields = data?.fields ?? [];
  const list = data ? (showAll ? data.rows : data.rows.slice(0, PREVIEW_ROWS)) : [];
  return (
    <div className="space-y-3" data-testid="batch-setup">
      <p className="text-sm text-slate-600">
        엑셀·CSV 한 장으로 여러 건을 한 번에 실행해요. 줄마다 흐름이 한 번씩 돌고, 결과는 표로 받을
        수 있어요.
        {note ? ` ${note}` : ""}
      </p>
      <ol className="space-y-2 text-sm">
        <li className="flex flex-wrap items-center gap-2">
          <span className="w-5 text-xs font-bold text-indigo-600">1</span>
          <Button size="sm" variant="outline" onClick={() => void download("template")}>
            <FileSpreadsheet className="h-3.5 w-3.5" /> 양식 내려받기
          </Button>
          <span className="text-xs text-slate-500">
            머리글은 그대로 두고 아래 줄에 값을 채워요.
          </span>
        </li>
        <li className="flex flex-wrap items-center gap-2">
          <span className="w-5 text-xs font-bold text-indigo-600">2</span>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.xlsx,.tsv,.txt"
            className="sr-only"
            aria-label="일괄 실행 파일 고르기"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) {
                setShowAll(false);
                preview.mutate(f);
              }
            }}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={preview.isPending}
            onClick={() => fileRef.current?.click()}
          >
            {preview.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Upload className="h-3.5 w-3.5" />
            )}
            {preview.isPending ? "읽는 중…" : "채운 파일 올리기"}
          </Button>
          <span className="text-xs text-slate-500">
            CSV·XLSX, 한 번에 최대 {data?.max_rows ?? "N"}건
          </span>
        </li>
      </ol>
      <ErrorBox error={preview.error} />
      {data && (
        <div className="space-y-2">
          <p className="text-sm">
            총 <b>{data.total}</b>줄 · 실행할 수 있는 줄{" "}
            <b className="text-emerald-700">{data.ok_count}</b>
            {data.error_count > 0 && (
              <>
                {" "}
                · 고칠 곳이 있는 줄 <b className="text-red-700">{data.error_count}</b>
              </>
            )}
          </p>
          {data.unmatched.length > 0 && (
            <p className="rounded bg-amber-50 px-3 py-2 text-xs text-amber-900">
              입력 칸과 이름이 맞지 않는 열은 쓰지 않아요: {data.unmatched.join(", ")}
            </p>
          )}
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full min-w-[480px] text-left text-xs">
              <thead className="bg-slate-50 text-slate-500">
                <tr>
                  <th className="w-12 px-2 py-1.5 font-medium">줄</th>
                  {fields.map((f) => (
                    <th key={f.key} className="px-2 py-1.5 font-medium">
                      {f.label || f.key}
                    </th>
                  ))}
                  <th className="px-2 py-1.5 font-medium">확인</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {list.map((r) => (
                  <tr key={r.row} className={r.errors.length ? "bg-red-50/60" : undefined}>
                    <td className="px-2 py-1.5 text-slate-500">{r.row}</td>
                    {fields.map((f) => (
                      <td key={f.key} className="px-2 py-1.5 text-slate-800">
                        {clip(show(r.values[f.key]), 40)}
                      </td>
                    ))}
                    <td className="px-2 py-1.5">
                      {r.errors.length === 0 ? (
                        <span className="text-emerald-700">✓</span>
                      ) : (
                        r.errors.map((e, i) => (
                          <div key={i} className="text-red-700">
                            <p className="font-medium">{e.message}</p>
                            <p>{e.hint}</p>
                          </div>
                        ))
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.rows.length > PREVIEW_ROWS && !showAll && (
            <button
              type="button"
              className="text-xs font-medium text-indigo-600 hover:underline"
              onClick={() => setShowAll(true)}
            >
              {data.rows.length - PREVIEW_ROWS}줄 더 보기
            </button>
          )}
          <ErrorBox error={create.error} />
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={data.error_count > 0 || create.isPending}
              onClick={() => run(false)}
            >
              {create.isPending ? "시작하는 중…" : `${data.total}건 실행하기`}
            </Button>
            {data.error_count > 0 && data.ok_count > 0 && (
              <Button
                size="sm"
                variant="outline"
                disabled={create.isPending}
                onClick={() => run(true)}
              >
                오류 줄은 빼고 {data.ok_count}건만 실행
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={reset}>
              다시 고르기
            </Button>
          </div>
          {data.error_count > 0 && (
            <p className="text-xs text-slate-500">
              고칠 곳이 있는 줄이 있으면 파일을 고쳐 다시 올리거나, 오류 줄을 빼고 실행하세요.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
