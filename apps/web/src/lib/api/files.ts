// 실행이 만든 파일 받기(v0.9). 로그인이 필요한 경로도 있어서 <a href> 대신 인증 헤더를 붙여 받은 뒤
// 브라우저 안에서 저장한다. 컴포넌트에서 fetch를 직접 쓰지 않도록 여기에 모아 둔다.
import { useQuery } from "@tanstack/react-query";
import { api, rawRequest, toApiError } from "@/lib/api/client";
import type { OutputFile } from "@/lib/fileKinds";

export async function fetchFileBlob(path: string, signal?: AbortSignal): Promise<Blob> {
  const res = await rawRequest(path, { signal });
  if (!res.ok) throw await toApiError(res);
  return res.blob();
}

/** 받은 내용을 파일로 저장하게 한다(브라우저의 '다운로드') */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export async function downloadFile(path: string, filename: string): Promise<void> {
  saveBlob(await fetchFileBlob(path), filename);
}

/** 실행 기록의 파일 목록(실행이 끝난 뒤 한 번 읽는다) */
export function useRunFiles(runId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["run-files", runId],
    queryFn: () => api.get<{ files: OutputFile[] }>(`/runs/${runId}/files`),
    enabled: Boolean(runId) && enabled,
    select: (d) => d.files,
  });
}
