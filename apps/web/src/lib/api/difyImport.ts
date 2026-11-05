// v0.8 Dify 앱 가져오기: 파일을 올리면 새 앱(초안)과 변환 보고서가 돌아온다.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { AppDetailV2 } from "@/lib/api/types";

export interface DifyReportItem {
  node: string;
  label: string;
  dify_type?: string;
  genio_type?: string;
  message?: string;
}

export interface DifyReport {
  mode: string;
  dify_version: string;
  converted: DifyReportItem[];
  needs_attention: DifyReportItem[];
  unsupported: DifyReportItem[];
  warnings: string[];
  validation_errors: { node: string; message: string }[];
  stats: {
    converted: number;
    needs_attention: number;
    unsupported: number;
    validation_errors: number;
  };
}

export interface DifyImportResult {
  app: AppDetailV2;
  report: DifyReport;
}

export const DIFY_MODE_LABEL: Record<string, string> = {
  workflow: "워크플로우",
  "advanced-chat": "챗플로우",
  chat: "챗봇",
  "agent-chat": "에이전트",
  completion: "문장 완성",
};

export function useImportDify(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { file: File; projectId?: string }) => {
      const form = new FormData();
      form.append("file", v.file);
      if (v.projectId) form.append("project_id", v.projectId);
      return api.upload<DifyImportResult>(`/workspaces/${ws}/apps/import-dify`, form);
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["apps", ws] }),
  });
}

/** 변환 보고서를 글 파일로 내려받을 수 있게 읽기 쉬운 글로 만든다. */
export function reportToText(appName: string, r: DifyReport): string {
  const lines: string[] = [];
  lines.push(`Dify 앱 가져오기 보고서 — ${appName}`);
  lines.push(
    `종류: ${DIFY_MODE_LABEL[r.mode] ?? r.mode}${r.dify_version ? ` (Dify DSL ${r.dify_version})` : ""}`,
  );
  lines.push(
    `바뀐 단계 ${r.stats.converted}개 · 확인할 곳 ${r.stats.needs_attention}곳 · 옮기지 못한 단계 ${r.stats.unsupported}개`,
  );
  const section = (title: string, items: string[]) => {
    if (!items.length) return;
    lines.push("", `[${title}]`, ...items.map((t) => `- ${t}`));
  };
  section(
    "확인해 주세요",
    r.needs_attention.map((i) => `${i.label}: ${i.message ?? ""}`),
  );
  section(
    "옮기지 못한 단계(꺼 둔 자리로 남겼어요)",
    r.unsupported.map((i) => `${i.label}: ${i.message ?? ""}`),
  );
  section("알림", r.warnings);
  section(
    "남은 설정 문제",
    r.validation_errors.map((e) => e.message),
  );
  section(
    "바뀐 단계",
    r.converted.map((i) => `${i.label} (${i.dify_type} → ${i.genio_type})`),
  );
  return lines.join("\n");
}
