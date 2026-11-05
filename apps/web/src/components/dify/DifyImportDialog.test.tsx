import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { DifyImportDialog, DifyReportView } from "@/components/dify/DifyImportDialog";
import { api } from "@/lib/api/client";
import { reportToText, type DifyImportResult, type DifyReport } from "@/lib/api/difyImport";
import type { AppDetailV2 } from "@/lib/api/types";

const REPORT: DifyReport = {
  mode: "workflow",
  dify_version: "0.1.5",
  converted: [
    { node: "n1", label: "시작", dify_type: "start", genio_type: "input" },
    { node: "n2", label: "AI 답변", dify_type: "llm", genio_type: "llm" },
  ],
  needs_attention: [
    { node: "n2", label: "AI 답변", message: "원래 모델: openai gpt-4o. 모델을 정해 주세요." },
  ],
  unsupported: [
    { node: "n3", label: "웹 검색", dify_type: "tool", message: "Dify 도구는 다시 만들어 주세요." },
  ],
  warnings: ["대화 변수(visit_count)의 처음 값은 옮기지 않아요."],
  validation_errors: [{ node: "n4", message: "입력 단계에서 이어지지 않은 단계예요." }],
  stats: { converted: 2, needs_attention: 1, unsupported: 1, validation_errors: 1 },
};
const RESULT = { app: { id: "a1", name: "혼합 흐름" } as AppDetailV2, report: REPORT };

function wrap(ui: React.ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
}

afterEach(() => vi.restoreAllMocks());

test("변환 보고서는 종류별 목록으로 보인다(JSON 없이)", () => {
  render(<DifyReportView result={RESULT as DifyImportResult} />);
  expect(screen.getByText("확인해 주세요")).toBeTruthy();
  expect(screen.getByText(/원래 모델: openai gpt-4o/)).toBeTruthy();
  expect(screen.getByText(/옮기지 못한 단계/, { selector: "h3" })).toBeTruthy();
  expect(screen.getByText("Dify tool")).toBeTruthy();
  expect(screen.getByText("빌더에서 고칠 곳")).toBeTruthy();
  expect(screen.getByText(/visit_count/)).toBeTruthy();
  expect(screen.getByText("바뀐 단계 2개 보기")).toBeTruthy();
  expect(screen.queryByText(/"stats"/)).toBeNull();
});

test("문제가 없으면 모두 옮겨졌다고 알린다", () => {
  const clean: DifyReport = {
    ...REPORT,
    needs_attention: [],
    unsupported: [],
    warnings: [],
    validation_errors: [],
    stats: { converted: 2, needs_attention: 0, unsupported: 0, validation_errors: 0 },
  };
  render(<DifyReportView result={{ ...RESULT, report: clean } as DifyImportResult} />);
  expect(screen.getByText(/모든 단계가 그대로 옮겨졌어요/)).toBeTruthy();
});

test("보고서 글 파일에는 확인할 곳·옮기지 못한 단계가 들어간다", () => {
  const text = reportToText("혼합 흐름", REPORT);
  expect(text).toContain("Dify 앱 가져오기 보고서 — 혼합 흐름");
  expect(text).toContain("[확인해 주세요]");
  expect(text).toContain("- AI 답변: 원래 모델: openai gpt-4o. 모델을 정해 주세요.");
  expect(text).toContain("[옮기지 못한 단계(꺼 둔 자리로 남겼어요)]");
  expect(text).toContain("- 웹 검색: Dify 도구는 다시 만들어 주세요.");
  expect(text).toContain("시작 (start → input)");
});

test("파일을 고르면 올리고, 끝나면 보고서와 '빌더에서 열기'가 나온다", async () => {
  const upload = vi.spyOn(api, "upload").mockResolvedValue(RESULT);
  render(wrap(<DifyImportDialog open onClose={() => undefined} projectId="p1" />));
  expect(screen.getByText(/파일을 끌어다 놓거나 눌러서 고르세요/)).toBeTruthy();
  const input = screen.getByLabelText("Dify 앱 파일") as HTMLInputElement;
  const file = new File(["app: {}"], "app.yml", { type: "text/yaml" });
  fireEvent.change(input, { target: { files: [file] } });
  await waitFor(() => expect(screen.getByTestId("dify-report")).toBeTruthy());
  expect(upload).toHaveBeenCalledTimes(1);
  const [path, form] = upload.mock.calls[0] as [string, FormData];
  expect(path).toMatch(/\/apps\/import-dify$/);
  expect((form.get("file") as File).name).toBe("app.yml");
  expect(form.get("project_id")).toBe("p1");
  expect(screen.getByRole("button", { name: "빌더에서 열기" })).toBeTruthy();
  expect(screen.getByRole("button", { name: /보고서 내려받기/ })).toBeTruthy();
});

test("올리기가 실패하면 두 줄 안내를 보여 준다", async () => {
  const { ApiError } = await import("@/lib/api/client");
  vi.spyOn(api, "upload").mockRejectedValue(
    new ApiError(
      422,
      "Dify에서 내보낸 앱 파일이 아니에요.",
      "Dify의 앱 화면에서 '내보내기(DSL)'로 받은 .yml 파일인지 확인하세요.",
    ),
  );
  render(wrap(<DifyImportDialog open onClose={() => undefined} />));
  const input = screen.getByLabelText("Dify 앱 파일") as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(["x"], "x.yml")] } });
  await waitFor(() => expect(screen.getByText(/Dify에서 내보낸 앱 파일이 아니에요/)).toBeTruthy());
  expect(screen.getByText(/내보내기\(DSL\)'로 받은/)).toBeTruthy();
});
