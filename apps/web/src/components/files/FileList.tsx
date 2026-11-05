// 실행이 만든 파일 보여 주기: 이미지는 그 자리에서 보이고(눌러 키우기·내려받기), 나머지는 내려받기 칩.
import {
  Download,
  File as FileIcon,
  FileSpreadsheet,
  FileText,
  FileType2,
  ImageOff,
  Loader2,
  ZoomIn,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Dialog } from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast-store";
import { downloadFile, fetchFileBlob } from "@/lib/api/files";
import {
  categoryOf,
  formatSize,
  splitFiles,
  type FileCategory,
  type OutputFile,
} from "@/lib/fileKinds";

/** 파일을 어느 경로로 받을지(공유 링크 토큰이 있으면 서명 링크). 받을 수 없으면 null */
export type ResolveFile = (f: OutputFile, inline: boolean) => string | null;

const ICON: Record<FileCategory, typeof FileIcon> = {
  image: FileIcon,
  sheet: FileSpreadsheet,
  doc: FileType2,
  text: FileText,
  other: FileIcon,
};

/** 인증 헤더가 필요할 수 있어 받아서 보여 준다(주소를 <img>에 바로 넣지 않는다). */
function useBlobUrl(path: string | null): { url: string | null; failed: boolean } {
  const [state, setState] = useState<{ url: string | null; failed: boolean }>({
    url: null,
    failed: false,
  });
  useEffect(() => {
    if (!path) {
      setState({ url: null, failed: true });
      return;
    }
    const ctrl = new AbortController();
    let made: string | null = null;
    setState({ url: null, failed: false });
    fetchFileBlob(path, ctrl.signal)
      .then((blob) => {
        made = URL.createObjectURL(blob);
        setState({ url: made, failed: false });
      })
      .catch(() => {
        if (!ctrl.signal.aborted) setState({ url: null, failed: true });
      });
    return () => {
      ctrl.abort();
      if (made) URL.revokeObjectURL(made);
    };
  }, [path]);
  return state;
}

async function save(file: OutputFile, path: string | null): Promise<void> {
  if (!path) {
    toast.error("이 파일은 지금 내려받을 수 없어요. 화면을 새로고침한 뒤 다시 시도하세요.");
    return;
  }
  try {
    await downloadFile(path, file.filename);
  } catch (err) {
    toast.error(err);
  }
}

function ImageTile({ file, resolve }: { file: OutputFile; resolve: ResolveFile }) {
  const path = resolve(file, true);
  const { url, failed } = useBlobUrl(path);
  const [open, setOpen] = useState(false);
  return (
    <>
      <div className="group relative overflow-hidden rounded-xl border border-slate-200 bg-slate-100">
        {url ? (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="block"
            aria-label={`${file.filename} 크게 보기`}
          >
            <img
              src={url}
              alt={file.filename}
              className="h-40 w-auto max-w-full object-cover sm:h-48"
              loading="lazy"
            />
          </button>
        ) : (
          <div className="flex h-40 w-40 items-center justify-center text-slate-400 sm:h-48 sm:w-48">
            {failed ? (
              <span className="flex flex-col items-center gap-1 px-2 text-center text-xs">
                <ImageOff className="h-5 w-5" /> 그림을 불러오지 못했어요
              </span>
            ) : (
              <Loader2 className="h-5 w-5 animate-spin" aria-label="그림을 불러오는 중" />
            )}
          </div>
        )}
        <div className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-1 bg-gradient-to-t from-black/60 to-transparent px-2 pb-1.5 pt-6 text-[11px] text-white opacity-100 sm:opacity-0 sm:transition-opacity sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
          <span className="truncate">{file.filename}</span>
          <span className="flex shrink-0 gap-1">
            <button
              type="button"
              onClick={() => setOpen(true)}
              disabled={!url}
              aria-label="크게 보기"
              className="rounded bg-white/20 p-1 hover:bg-white/40 disabled:opacity-40"
            >
              <ZoomIn className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => void save(file, resolve(file, false))}
              aria-label={`${file.filename} 내려받기`}
              className="rounded bg-white/20 p-1 hover:bg-white/40"
            >
              <Download className="h-3.5 w-3.5" />
            </button>
          </span>
        </div>
      </div>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={file.filename}
        wide
        footer={
          <button
            type="button"
            onClick={() => void save(file, resolve(file, false))}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500"
          >
            <Download className="h-4 w-4" /> 내려받기
          </button>
        }
      >
        {url && (
          <img src={url} alt={file.filename} className="mx-auto max-h-[70vh] w-auto rounded-lg" />
        )}
      </Dialog>
    </>
  );
}

function FileChip({ file, resolve }: { file: OutputFile; resolve: ResolveFile }) {
  const [busy, setBusy] = useState(false);
  const Icon = ICON[categoryOf(file.mime, file.filename)];
  const size = formatSize(file.size);
  return (
    <button
      type="button"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await save(file, resolve(file, false));
        } finally {
          setBusy(false);
        }
      }}
      className="inline-flex max-w-full items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-left text-sm shadow-sm transition-colors hover:border-indigo-300 hover:bg-indigo-50/40 disabled:opacity-60"
      aria-label={`${file.filename} 내려받기`}
    >
      <Icon className="h-5 w-5 shrink-0 text-indigo-500" />
      <span className="min-w-0">
        <span className="block truncate font-medium text-slate-800">{file.filename}</span>
        {size && <span className="block text-[11px] text-slate-500">{size}</span>}
      </span>
      {busy ? (
        <Loader2 className="h-4 w-4 shrink-0 animate-spin text-slate-400" />
      ) : (
        <Download className="h-4 w-4 shrink-0 text-slate-400" />
      )}
    </button>
  );
}

export function FileList({
  files,
  resolve,
  className = "",
}: {
  files: OutputFile[] | undefined;
  resolve: ResolveFile;
  className?: string;
}) {
  if (!files || files.length === 0) return null;
  const { images, others } = splitFiles(files);
  return (
    <div className={`space-y-2 ${className}`} data-testid="output-files">
      {images.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {images.map((f) => (
            <ImageTile key={f.id} file={f} resolve={resolve} />
          ))}
        </div>
      )}
      {others.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {others.map((f) => (
            <FileChip key={f.id} file={f} resolve={resolve} />
          ))}
        </div>
      )}
    </div>
  );
}
