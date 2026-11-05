// v0.8 단계 하나만 시험: 이 단계가 쓰는 앞 단계 값을 채우고, 그 값으로 단계만 실행해 본다.
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export type TestValueKind = "string" | "number" | "boolean" | "json" | "empty";

export interface TestField {
  field: string;
  /** `{{단계.값}}` 형식 */
  path: string;
  value: unknown;
  kind: TestValueKind;
  from_last_run: boolean;
}

export interface TestGroup {
  /** 앞 단계 id, 또는 input(입력 값)·conv(대화 값) */
  scope: string;
  label: string;
  editable: boolean;
  fields: TestField[];
}

export interface NodeTestInputs {
  node_id: string;
  type: string;
  label: string;
  testable: boolean;
  reason: string | null;
  /** 실제로 일어나는 일(비용·바깥 요청) 안내 */
  warn: string | null;
  /** true면 실행 전에 한 번 더 확인한다(메일 보내기·데이터 저장 등) */
  risky: boolean;
  last_run_id: string | null;
  groups: TestGroup[];
}

export interface NodeTestResult {
  node_id: string;
  ok: boolean;
  output: Record<string, unknown> | null;
  handle: string | null;
  summary: string;
  error: { message: string; hint: string } | null;
  ms: number;
  logs: string[];
  tokens: { input_tokens: number; output_tokens: number };
}

export function useNodeTestInputs(appId: string) {
  return useMutation({
    mutationFn: (v: { nodeId: string; data: Record<string, unknown> }) =>
      api.post<NodeTestInputs>(`/apps/${appId}/nodes/${v.nodeId}/test-inputs`, { data: v.data }),
  });
}

export function useRunNodeTest(appId: string) {
  return useMutation({
    mutationFn: (v: {
      nodeId: string;
      data: Record<string, unknown>;
      values: Record<string, Record<string, unknown>>;
    }) =>
      api.post<NodeTestResult>(`/apps/${appId}/nodes/${v.nodeId}/test`, {
        data: v.data,
        values: v.values,
      }),
  });
}

/** 입력칸의 글을 원래 값의 형식으로 되돌린다(숫자·참거짓·목록·객체). 안 되면 글 그대로. */
export function parseTestValue(text: string, kind: TestValueKind): unknown {
  if (kind === "number") {
    const n = Number(text);
    return text.trim() !== "" && Number.isFinite(n) ? n : text;
  }
  if (kind === "boolean") {
    const t = text.trim().toLowerCase();
    if (["true", "예", "참", "1"].includes(t)) return true;
    if (["false", "아니요", "거짓", "0"].includes(t)) return false;
    return text;
  }
  if (kind === "json") {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return text;
}

/** 화면 입력칸에 넣을 글 */
export function testValueText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 0);
}
