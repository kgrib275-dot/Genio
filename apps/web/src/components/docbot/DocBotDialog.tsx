import { FileText, Upload, X } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { createChatbotFromFiles, type DocBotProgress } from "@/lib/api/docBot";
import { ApiError, errorLines } from "@/lib/api/client";
import { useSession } from "@/store/session";

const STEP_TEXT: Record<DocBotProgress["step"], string> = {
  kb: "문서 보관함을 만드는 중…",
  upload: "문서를 올리는 중…",
  bot: "챗봇을 만드는 중…",
};

/** 문서를 올리면 그 문서로 답하는 챗봇을 바로 만들어 주는 마법사 */
export function DocBotDialog({
  open,
  onClose,
  projectId,
}: {
  open: boolean;
  onClose: () => void;
  projectId?: string;
}) {
  const ws = useSession((s) => s.workspaceId);
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState<DocBotProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    const next = [...files];
    for (const f of Array.from(list)) {
      if (!next.some((x) => x.name === f.name && x.size === f.size)) next.push(f);
    }
    setFiles(next.slice(0, 20));
    const first = next[0];
    if (!name.trim() && first) setName(first.name.replace(/\.[^.]+$/, ""));
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy || files.length === 0) return;
    setError(null);
    setBusy({ step: "kb", done: 0, total: files.length });
    try {
      const { app, failed } = await createChatbotFromFiles({
        ws,
        name: name.trim() || "내 문서",
        files,
        projectId,
        onProgress: setBusy,
      });
      if (failed.length > 0) {
        toast.error(
          `올리지 못한 파일이 있어요: ${failed.join(", ")}. 지식베이스 화면에서 다시 올려 보세요.`,
        );
      } else {
        toast.success("챗봇을 만들었어요. 위쪽 '대화로 시험'으로 물어보세요.");
      }
      onClose();
      navigate(`/apps/${app.id}/builder`);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.hint ? `${err.message} ${err.hint}` : err.message);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        const { message, hint } = errorLines(err);
        setError(`${message} ${hint}`);
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <Dialog open={open} onClose={busy ? () => undefined : onClose} title="문서로 챗봇 만들기">
      <form onSubmit={(e) => void submit(e)} className="space-y-4">
        <p className="text-sm text-slate-600">
          규정집·매뉴얼·FAQ 같은 문서를 올리면, 그 내용으로 답하는 챗봇을 바로 만들어 드려요.
          (PDF·Word·파워포인트·엑셀·텍스트)
        </p>
        <Field
          label="챗봇에 붙일 이름"
          htmlFor="docbot-name"
          hint="비우면 첫 문서 이름으로 정해요."
        >
          <Input
            id="docbot-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="예: 휴가 규정"
            maxLength={60}
          />
        </Field>
        <div>
          <input
            ref={inputRef}
            type="file"
            multiple
            className="hidden"
            aria-label="문서 고르기"
            accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.csv,.html"
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <button
            type="button"
            className="flex w-full flex-col items-center gap-1 rounded-xl border-2 border-dashed border-slate-300 px-4 py-6 text-sm text-slate-600 hover:border-indigo-300 hover:bg-indigo-50/40"
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              addFiles(e.dataTransfer.files);
            }}
          >
            <Upload className="h-5 w-5 text-indigo-500" />
            <span className="font-medium">문서를 끌어 놓거나 눌러서 고르세요</span>
            <span className="text-xs text-slate-400">한 번에 20개까지</span>
          </button>
          {files.length > 0 && (
            <ul className="mt-2 space-y-1" aria-label="고른 문서">
              {files.map((f) => (
                <li
                  key={f.name + f.size}
                  className="flex items-center gap-2 rounded-lg bg-slate-50 px-2.5 py-1.5 text-sm"
                >
                  <FileText className="h-4 w-4 shrink-0 text-slate-400" />
                  <span className="min-w-0 flex-1 truncate">{f.name}</span>
                  <button
                    type="button"
                    aria-label={`${f.name} 빼기`}
                    className="rounded p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
                    onClick={() => setFiles(files.filter((x) => x !== f))}
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {error && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800">
            {error}
          </p>
        )}
        <div className="flex items-center justify-end gap-2">
          {busy && (
            <span className="mr-auto text-xs text-slate-500" aria-live="polite">
              {STEP_TEXT[busy.step]}
              {busy.step === "upload" ? ` (${busy.done}/${busy.total})` : ""}
            </span>
          )}
          <Button type="button" variant="outline" onClick={onClose} disabled={Boolean(busy)}>
            닫기
          </Button>
          <Button type="submit" disabled={files.length === 0 || Boolean(busy)}>
            챗봇 만들기
          </Button>
        </div>
        <p className="text-xs text-slate-400">
          문서는 이 워크스페이스에만 저장돼요. 문서를 검색할 수 있게 처리하려면 AI 연결이 필요해요
          (키가 없으면 데모 AI로 먼저 훑어볼 수 있어요).
        </p>
      </form>
    </Dialog>
  );
}
