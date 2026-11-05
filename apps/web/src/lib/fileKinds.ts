// 실행이 만든 파일(이미지 만들기·파일 만들기, v0.9)을 화면에 보이는 데 쓰는 순수 도구들.

/** 서버가 답·결과·실행 상세에 실어 보내는 파일 하나 */
export interface OutputFile {
  id: string;
  filename: string;
  mime: string;
  size: number;
  kind: "image" | "file";
  /** 어느 실행이 만들었는지(로그인한 화면이 실행 기록 경로로 받을 때) */
  run_id?: string;
  /** 공유 화면용 서명 링크(없으면 로그인한 화면용) */
  sig?: string;
  exp?: number;
  /** 만든 단계(실행 상세에서만) */
  node_id?: string;
}

/** 실행 상세 응답에 붙어 오는 파일 목록(타입 파일을 건드리지 않으려고 따로 둔다) */
export interface WithFiles {
  files?: OutputFile[];
}

export type FileCategory = "image" | "sheet" | "doc" | "text" | "other";

const SHEET = ["spreadsheetml", "csv", "ms-excel"];
const DOC = ["wordprocessingml", "msword", "pdf"];

export function categoryOf(mime: string, filename = ""): FileCategory {
  const m = mime.toLowerCase();
  const n = filename.toLowerCase();
  if (m.startsWith("image/")) return "image";
  if (SHEET.some((k) => m.includes(k)) || /\.(xlsx|xls|csv)$/.test(n)) return "sheet";
  if (DOC.some((k) => m.includes(k)) || /\.(docx|doc|pdf)$/.test(n)) return "doc";
  if (m.startsWith("text/") || m.includes("json") || /\.(txt|md|json)$/.test(n)) return "text";
  return "other";
}

export const CATEGORY_LABEL: Record<FileCategory, string> = {
  image: "이미지",
  sheet: "표",
  doc: "문서",
  text: "글",
  other: "파일",
};

export function formatSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

/** 로그인한 사람이 실행 기록에서 받는 경로(API 접두사 제외) */
export function runFilePath(runId: string, fileId: string, inline = false): string {
  return `/runs/${encodeURIComponent(runId)}/files/${encodeURIComponent(fileId)}${inline ? "?inline=1" : ""}`;
}

/** 공유 링크의 서명된 내려받기 경로(API 접두사 제외) */
export function publicFilePath(token: string, f: OutputFile, inline = false): string {
  const q = `sig=${encodeURIComponent(f.sig ?? "")}&exp=${f.exp ?? 0}${inline ? "&inline=1" : ""}`;
  return `/public/apps/${encodeURIComponent(token)}/files/${encodeURIComponent(f.id)}?${q}`;
}

/** 어느 경로로 받을지: 공유 화면(토큰 + 서명)이면 공개 경로, 아니면 실행 기록 경로. 받을 수 없으면 null */
export function resolveFilePath(
  f: OutputFile,
  ctx: { token?: string },
  inline = false,
): string | null {
  if (ctx.token && f.sig) return publicFilePath(ctx.token, f, inline);
  if (f.run_id) return runFilePath(f.run_id, f.id, inline);
  return null;
}

/** 일괄 실행 결과 줄의 파일을 받을 경로: 로그인한 화면은 실행 기록, 공유 링크는 서명된 주소 */
export function batchFilePath(
  row: { run_id?: string },
  f: { id: string; url?: string },
): string | null {
  if (row.run_id) return runFilePath(row.run_id, f.id);
  if (f.url) {
    try {
      const u = new URL(f.url, "http://local");
      if (u.pathname.startsWith("/api/")) return u.pathname + u.search;
    } catch {
      return null;
    }
  }
  return null;
}

/** 한 번에 이미지만/파일만 가르기(이미지는 미리 보기, 나머지는 내려받기 칩) */
export function splitFiles(files: OutputFile[]): { images: OutputFile[]; others: OutputFile[] } {
  const images = files.filter(
    (f) => f.kind === "image" || categoryOf(f.mime, f.filename) === "image",
  );
  const ids = new Set(images.map((f) => f.id));
  return { images, others: files.filter((f) => !ids.has(f.id)) };
}
