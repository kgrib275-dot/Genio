// 데이터 표의 줄: 서버에서 검색·페이지, 줄 안에서 바로 고치기, CSV 가져오기·내보내기
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Pencil,
  Plus,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast-store";
import type { DataColumn, DataRow, DataTable } from "@/lib/api/types";
import {
  downloadDataTableCsv,
  useCreateRow,
  useDataRows,
  useDeleteRow,
  useImportCsv,
  useUpdateRow,
} from "@/lib/api/v4";
import { cn, formatDate } from "@/lib/cn";
import { display, fromText, toText } from "@/pages/data/values";

const SIZES = [10, 20, 50, 100];
const SIZE_KEY = "genio.list.data-rows.size";

function readSize(): number {
  try {
    const n = Number(window.localStorage.getItem(SIZE_KEY));
    return SIZES.includes(n) ? n : 20;
  } catch {
    return 20;
  }
}

interface Draft {
  /** 새 줄이면 null */
  id: string | null;
  rowKey: string;
  values: Record<string, string>;
}

function draftOf(row: DataRow | null, cols: DataColumn[]): Draft {
  return {
    id: row?.id ?? null,
    rowKey: row?.row_key ?? "",
    values: Object.fromEntries(cols.map((c) => [c.key, toText(row?.data[c.key], c.type)])),
  };
}

function CellInput({
  col,
  value,
  onChange,
  invalid,
}: {
  col: DataColumn;
  value: string;
  onChange: (v: string) => void;
  invalid?: boolean;
}) {
  const cls = cn(
    "w-full min-w-[7rem] rounded-md border bg-white px-2 py-1 text-[13px] focus:border-indigo-500 focus:outline-none",
    invalid ? "border-red-400" : "border-slate-300",
  );
  if (col.type === "boolean")
    return (
      <select
        aria-label={col.label}
        className={cls}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">-</option>
        <option value="true">예</option>
        <option value="false">아니오</option>
      </select>
    );
  if (col.type === "json")
    return (
      <textarea
        aria-label={col.label}
        className={cn(cls, "min-h-[56px] font-mono text-[11px]")}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  return (
    <input
      aria-label={col.label}
      className={cls}
      type={col.type === "number" ? "text" : col.type === "date" ? "date" : "text"}
      inputMode={col.type === "number" ? "decimal" : undefined}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export function RowsGrid({
  ws,
  table,
  canEditRows,
  canEditTable,
}: {
  ws: string;
  table: DataTable;
  canEditRows: boolean;
  canEditTable: boolean;
}) {
  const cols = table.columns;
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(readSize);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const fileRef = useRef<HTMLInputElement>(null);

  // 검색어는 치는 동안 잠깐 기다렸다가 서버에 묻는다
  useEffect(() => {
    const t = window.setTimeout(() => {
      setQ(qInput);
      setPage(1);
    }, 300);
    return () => window.clearTimeout(t);
  }, [qInput]);

  // 다른 표로 바꾸면 처음부터
  useEffect(() => {
    setQInput("");
    setQ("");
    setPage(1);
    setDraft(null);
  }, [table.id]);

  const rows = useDataRows(table.id, { limit: size, offset: (page - 1) * size, q });
  const create = useCreateRow(table.id);
  const update = useUpdateRow(table.id);
  const del = useDeleteRow(table.id);
  const importCsv = useImportCsv(ws, table.id);
  const total = rows.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / size));
  const saving = create.isPending || update.isPending;

  useEffect(() => {
    if (page > pages) setPage(pages);
  }, [page, pages]);

  const save = () => {
    if (!draft) return;
    const data: Record<string, unknown> = {};
    const errs: Record<string, string> = {};
    for (const c of cols) {
      const r = fromText(draft.values[c.key] ?? "", c.type);
      if (r.ok) data[c.key] = r.value;
      else errs[c.key] = r.error;
    }
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const rowKey = draft.rowKey.trim() || null;
    const done = () => {
      setDraft(null);
      toast.success(draft.id ? "줄을 고쳤어요." : "줄을 넣었어요.");
    };
    if (draft.id) {
      // 표에 없는 칸의 값은 지우지 않고 그대로 둔다
      const old = rows.data?.rows.find((r) => r.id === draft.id)?.data ?? {};
      update.mutate(
        { id: draft.id, row_key: rowKey, data: { ...old, ...data } },
        { onSuccess: done },
      );
    } else create.mutate({ row_key: rowKey, data }, { onSuccess: done });
  };

  const editingRow = (r: DataRow) => draft?.id === r.id;
  const colCount = cols.length + 3;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[160px] flex-1 sm:max-w-xs" role="search">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="search"
            aria-label="값 검색"
            placeholder="값 검색"
            value={qInput}
            onChange={(e) => setQInput(e.target.value)}
            className="h-9 w-full rounded-lg border border-slate-300 bg-white pl-8 pr-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/15"
          />
        </div>
        <div className="ml-auto flex flex-wrap gap-1.5">
          {canEditRows && (
            <Button
              size="sm"
              disabled={Boolean(draft && !draft.id)}
              onClick={() => {
                setErrors({});
                setDraft(draftOf(null, cols));
              }}
            >
              <Plus className="h-3.5 w-3.5" /> 줄 추가
            </Button>
          )}
          {canEditTable && (
            <>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (!f) return;
                  importCsv.mutate(f, {
                    onSuccess: (r) => toast.success(`${r.imported}줄을 가져왔어요.`),
                    onError: (err) => toast.error(err),
                  });
                }}
              />
              <Button
                size="sm"
                variant="outline"
                disabled={importCsv.isPending}
                onClick={() => fileRef.current?.click()}
              >
                <Upload className="h-3.5 w-3.5" />
                {importCsv.isPending ? "가져오는 중…" : "CSV 가져오기"}
              </Button>
            </>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              downloadDataTableCsv(table).catch((err: unknown) => toast.error(err));
            }}
          >
            <Download className="h-3.5 w-3.5" /> CSV 내보내기
          </Button>
        </div>
      </div>

      <ErrorBox error={rows.error ?? create.error ?? update.error ?? del.error} />

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full min-w-max text-left text-[13px]">
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr>
              <th
                className="px-3 py-2 font-medium"
                title="같은 키로 다시 넣으면 새 줄 대신 덮어써요"
              >
                고유 키
              </th>
              {cols.map((c) => (
                <th key={c.key} className="px-3 py-2 font-medium" title={`키: ${c.key}`}>
                  {c.label || c.key}
                </th>
              ))}
              <th className="px-3 py-2 font-medium">바꾼 때</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {draft && !draft.id && (
              <EditRow
                cols={cols}
                draft={draft}
                errors={errors}
                saving={saving}
                onChange={setDraft}
                onSave={save}
                onCancel={() => setDraft(null)}
              />
            )}
            {(rows.data?.rows ?? []).map((r) =>
              editingRow(r) && draft ? (
                <EditRow
                  key={r.id}
                  cols={cols}
                  draft={draft}
                  errors={errors}
                  saving={saving}
                  onChange={setDraft}
                  onSave={save}
                  onCancel={() => setDraft(null)}
                />
              ) : (
                <tr key={r.id} className="hover:bg-slate-50/70">
                  <td className="px-3 py-2 font-mono text-xs text-slate-500">
                    {r.row_key ?? <span className="text-slate-300">-</span>}
                  </td>
                  {cols.map((c) => (
                    <td
                      key={c.key}
                      className="max-w-[16rem] truncate px-3 py-2 text-slate-800"
                      title={display(r.data[c.key], c.type)}
                    >
                      {display(r.data[c.key], c.type) || <span className="text-slate-300">-</span>}
                    </td>
                  ))}
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-400">
                    {formatDate(r.updated_at)}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1 text-right">
                    {canEditRows && (
                      <>
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label="이 줄 고치기"
                          title="고치기"
                          onClick={() => {
                            setErrors({});
                            setDraft(draftOf(r, cols));
                          }}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-red-600"
                          aria-label="이 줄 지우기"
                          title="지우기"
                          disabled={del.isPending}
                          onClick={() => {
                            if (window.confirm("이 줄을 지울까요?"))
                              del.mutate(r.id, { onError: (err) => toast.error(err) });
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </>
                    )}
                  </td>
                </tr>
              ),
            )}
            {rows.data && rows.data.rows.length === 0 && !draft && (
              <tr>
                <td colSpan={colCount} className="px-4 py-10 text-center text-sm text-slate-500">
                  {q ? (
                    <>
                      &apos;{q}&apos;가 들어간 줄이 없어요.
                      <br />
                      <button
                        type="button"
                        className="mt-1 font-medium text-indigo-600 hover:underline"
                        onClick={() => setQInput("")}
                      >
                        검색어 지우기
                      </button>
                    </>
                  ) : (
                    <>
                      아직 줄이 없어요.
                      <br />
                      {canEditRows
                        ? "줄 추가로 직접 넣거나, CSV 가져오기로 한 번에 넣거나, 흐름의 데이터 표 블록으로 쌓으세요."
                        : "흐름이 값을 넣으면 여기에 보여요."}
                    </>
                  )}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span>
          {total === 0
            ? "0줄"
            : `${total.toLocaleString()}줄 중 ${(page - 1) * size + 1}–${Math.min(page * size, total)}`}
          {rows.isFetching && " · 불러오는 중…"}
        </span>
        <div className="flex items-center gap-2">
          <select
            aria-label="한 번에 볼 개수"
            value={size}
            onChange={(e) => {
              const n = Number(e.target.value);
              setSize(n);
              setPage(1);
              try {
                window.localStorage.setItem(SIZE_KEY, String(n));
              } catch {
                // 기억하지 못해도 동작에는 문제없다
              }
            }}
            className="h-8 rounded-md border border-slate-300 bg-white px-1.5 text-xs text-slate-700"
          >
            {SIZES.map((n) => (
              <option key={n} value={n}>
                {n}줄
              </option>
            ))}
          </select>
          <button
            type="button"
            aria-label="이전 페이지"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
            className="rounded-md p-1.5 hover:bg-slate-100 disabled:opacity-30"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="min-w-[3.5rem] text-center tabular-nums">
            {page} / {pages}
          </span>
          <button
            type="button"
            aria-label="다음 페이지"
            disabled={page >= pages}
            onClick={() => setPage(page + 1)}
            className="rounded-md p-1.5 hover:bg-slate-100 disabled:opacity-30"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

function EditRow({
  cols,
  draft,
  errors,
  saving,
  onChange,
  onSave,
  onCancel,
}: {
  cols: DataColumn[];
  draft: Draft;
  errors: Record<string, string>;
  saving: boolean;
  onChange: (d: Draft) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <tr
      className="bg-indigo-50/60 align-top"
      onKeyDown={(e) => {
        if (e.key === "Escape") onCancel();
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) onSave();
      }}
    >
      <td className="px-2 py-1.5">
        <input
          aria-label="고유 키"
          placeholder="(없음)"
          value={draft.rowKey}
          onChange={(e) => onChange({ ...draft, rowKey: e.target.value })}
          className="w-full min-w-[6rem] rounded-md border border-slate-300 bg-white px-2 py-1 font-mono text-xs focus:border-indigo-500 focus:outline-none"
        />
      </td>
      {cols.map((c) => (
        <td key={c.key} className="px-2 py-1.5">
          <CellInput
            col={c}
            value={draft.values[c.key] ?? ""}
            invalid={Boolean(errors[c.key])}
            onChange={(v) => onChange({ ...draft, values: { ...draft.values, [c.key]: v } })}
          />
          {errors[c.key] && <p className="mt-0.5 text-[11px] text-red-600">{errors[c.key]}</p>}
        </td>
      ))}
      <td className="px-2 py-1.5 text-[11px] text-slate-400">{draft.id ? "고치는 중" : "새 줄"}</td>
      <td className="whitespace-nowrap px-2 py-1.5 text-right">
        <Button size="sm" onClick={onSave} disabled={saving}>
          {saving ? "저장 중…" : "저장"}
        </Button>
        <Button size="sm" variant="ghost" aria-label="취소" onClick={onCancel}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </td>
    </tr>
  );
}
