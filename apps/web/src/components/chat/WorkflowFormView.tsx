// 워크플로우 앱을 공유 링크로 열면 보이는 화면: 입력 폼 → 실행 → 결과.
import { CheckCircle2, Loader2, Paperclip, Play, RotateCcw, X } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type ReactNode,
} from "react";
import { AppIcon } from "@/components/AppIcon";
import { Markdown } from "@/components/chat/Markdown";
import { errorLines } from "@/lib/api/client";
import { startFormRun, waitFormResult, type FormRunResult } from "@/lib/api/form";
import type { PublicApp, StoredFile } from "@/lib/api/types";
import { uploadPublicFile } from "@/lib/api/v2";
import { cn } from "@/lib/cn";

type Field = PublicApp["input_fields"][number];

export function WorkflowFormView({
  token,
  title,
  icon,
  description,
  fields,
  accent,
  headerActions,
}: {
  token: string;
  title: string;
  icon?: string;
  description?: string;
  fields: Field[];
  accent?: string;
  headerActions?: ReactNode;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<FormRunResult | null>(null);
  const [error, setError] = useState<{ message: string; hint: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => () => abortRef.current?.abort(), []);

  const textFields = fields.filter((f) => f.type !== "file");
  const fileField = fields.find((f) => f.type === "file");
  const missing = textFields.filter((f) => f.required && !String(values[f.key] ?? "").trim());

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (missing.length || running) return;
    setRunning(true);
    setError(null);
    setResult(null);
    const ctl = new AbortController();
    abortRef.current = ctl;
    try {
      const input: Record<string, unknown> = {};
      for (const f of textFields) {
        const v = values[f.key] ?? "";
        input[f.key] = f.type === "number" && v !== "" ? Number(v) : v;
      }
      const started = await startFormRun(
        token,
        input,
        files.map((f) => f.id),
      );
      const r = await waitFormResult(token, started.run_id, ctl.signal, setResult);
      setResult(r);
    } catch (err) {
      if ((err as Error)?.name !== "AbortError") setError(errorLines(err));
    } finally {
      setRunning(false);
    }
  };

  const attach = async (list: FileList | null) => {
    if (!list?.length) return;
    setUploading(true);
    try {
      const up: StoredFile[] = [];
      for (const f of Array.from(list).slice(0, 3)) up.push(await uploadPublicFile(token, f));
      setFiles((fs) => [...fs, ...up].slice(0, 3));
    } catch (err) {
      setError(errorLines(err));
    } finally {
      setUploading(false);
    }
  };

  const done = result && (result.status === "succeeded" || result.status === "failed");
  const style = accent ? ({ "--accent": accent } as CSSProperties) : undefined;

  return (
    <div className="flex h-full flex-col bg-slate-50" style={style}>
      <header className="flex shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-3 py-2.5 sm:px-4">
        <AppIcon name={title} icon={icon} size="sm" />
        <p className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</p>
        {headerActions}
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl space-y-4 px-4 py-6">
          {description && <p className="text-sm text-slate-600">{description}</p>}
          <form
            onSubmit={submit}
            className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-card"
          >
            {textFields.length === 0 && !fileField && (
              <p className="text-sm text-slate-500">입력할 것이 없어요. 바로 실행해 보세요.</p>
            )}
            {textFields.map((f) => {
              const long = f.type === "paragraph" || f.key === "message";
              const id = `form-${f.key}`;
              return (
                <div key={f.key}>
                  <label htmlFor={id} className="mb-1 block text-sm font-medium text-slate-700">
                    {f.label || f.key}
                    {f.required && <span className="ml-0.5 text-red-500">*</span>}
                  </label>
                  {long ? (
                    <textarea
                      id={id}
                      rows={4}
                      value={values[f.key] ?? ""}
                      onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/15"
                    />
                  ) : (
                    <input
                      id={id}
                      type={f.type === "number" ? "number" : "text"}
                      value={values[f.key] ?? ""}
                      onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                      className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/15"
                    />
                  )}
                </div>
              );
            })}
            {fileField && (
              <div>
                <p className="mb-1 text-sm font-medium text-slate-700">
                  {fileField.label || "파일"}
                </p>
                <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-dashed border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50">
                  <Paperclip className="h-4 w-4" />
                  {uploading ? "올리는 중…" : "파일 고르기"}
                  <input
                    type="file"
                    className="sr-only"
                    multiple
                    onChange={(e) => void attach(e.target.files)}
                  />
                </label>
                {files.length > 0 && (
                  <ul className="mt-2 space-y-1 text-xs">
                    {files.map((f) => (
                      <li key={f.id} className="flex items-center gap-1.5 text-slate-600">
                        <Paperclip className="h-3 w-3" />
                        <span className="truncate">{f.filename}</span>
                        <button
                          type="button"
                          aria-label={`${f.filename} 빼기`}
                          onClick={() => setFiles((fs) => fs.filter((x) => x.id !== f.id))}
                          className="rounded p-0.5 hover:bg-slate-100"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            <div className="flex items-center gap-2">
              <button
                type="submit"
                disabled={running || missing.length > 0}
                className="inline-flex h-10 items-center gap-1.5 rounded-lg bg-[var(--accent,#4f46e5)] px-4 text-sm font-semibold text-white shadow-sm disabled:opacity-50"
              >
                {running ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                {running ? "실행하는 중…" : "실행하기"}
              </button>
              {missing.length > 0 && (
                <span className="text-xs text-slate-500">
                  {missing.map((f) => f.label || f.key).join(", ")}을(를) 채워 주세요.
                </span>
              )}
            </div>
          </form>

          {error && (
            <div
              role="alert"
              className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm"
            >
              <p className="font-medium text-red-800">{error.message}</p>
              <p className="text-red-700">{error.hint}</p>
            </div>
          )}

          {result && (
            <section
              aria-live="polite"
              className={cn(
                "rounded-2xl border bg-white p-5 shadow-card",
                result.status === "failed" ? "border-red-200" : "border-slate-200",
              )}
            >
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
                {result.status === "succeeded" ? (
                  <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                ) : result.status === "failed" ? (
                  <X className="h-4 w-4 text-red-500" />
                ) : (
                  <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />
                )}
                {result.status === "succeeded"
                  ? "결과"
                  : result.status === "failed"
                    ? "실행하지 못했어요"
                    : result.status === "waiting_approval"
                      ? "담당자 확인을 기다리는 중"
                      : "실행하는 중"}
              </div>
              {result.status === "failed" && result.error ? (
                <div className="text-sm">
                  <p className="text-red-800">{result.error.message}</p>
                  <p className="text-red-700">{result.error.hint}</p>
                  {result.error.detail && (
                    <p className="mt-2 text-xs text-slate-500">자세히: {result.error.detail}</p>
                  )}
                </div>
              ) : result.text ? (
                <Markdown text={result.text} />
              ) : null}
              {done && (
                <button
                  type="button"
                  onClick={() => setResult(null)}
                  className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:underline"
                >
                  <RotateCcw className="h-3.5 w-3.5" /> 다시 입력하기
                </button>
              )}
            </section>
          )}
        </div>
      </main>
    </div>
  );
}
