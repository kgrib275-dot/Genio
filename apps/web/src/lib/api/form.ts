// 워크플로우 앱 공유 화면(입력 폼 → 결과). 기능 정의서 Part 1 §2 앱 유형.
import { api } from "@/lib/api/client";
import type { OutputFile } from "@/lib/fileKinds";

export interface FormRunStarted {
  run_id: string;
  status: string;
}

export interface FormRunResult {
  run_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "waiting_approval" | string;
  text?: string;
  /** v0.9: 이미지·파일 단계가 만든 파일(서명 링크 포함) */
  files?: OutputFile[];
  error?: { message: string; hint: string; detail?: string };
}

export function startFormRun(
  token: string,
  input: Record<string, unknown>,
  files: string[] = [],
): Promise<FormRunStarted> {
  return api.post<FormRunStarted>(`/public/apps/${token}/runs`, { input, files });
}

export function getFormResult(token: string, runId: string): Promise<FormRunResult> {
  return api.get<FormRunResult>(`/public/apps/${token}/runs/${runId}`);
}

const DONE = new Set(["succeeded", "failed"]);

/** 결과가 나올 때까지 짧게 되묻는다(서버가 DB 연결을 붙잡지 않게). 확인을 기다리면 그대로 돌려준다. */
export async function waitFormResult(
  token: string,
  runId: string,
  signal: AbortSignal,
  onUpdate: (r: FormRunResult) => void,
): Promise<FormRunResult> {
  let delay = 400;
  for (;;) {
    if (signal.aborted) throw new DOMException("멈춤", "AbortError");
    const r = await getFormResult(token, runId);
    onUpdate(r);
    if (DONE.has(r.status)) return r;
    await new Promise((ok) => setTimeout(ok, delay));
    delay = Math.min(delay * 1.5, r.status === "waiting_approval" ? 8000 : 2000);
  }
}
