// 빌더 SSE 이벤트를 진행 중인 어시스턴트 턴 상태로 모은다.
import type { SSEEvent } from "@/lib/api/sse";
import type { AskUser, MarketSuggestion, TestResult, ToolCallRecord } from "@/lib/api/types";

export interface DraftTurn {
  text: string;
  tool_calls: ToolCallRecord[];
  ask_user?: AskUser;
  market_suggestion?: MarketSuggestion;
  test_result?: TestResult;
  error?: { message: string; hint?: string };
}

export const emptyDraft = (): DraftTurn => ({ text: "", tool_calls: [] });

export function reduceDraft(draft: DraftTurn, ev: SSEEvent): DraftTurn {
  const d = (ev.data ?? {}) as Record<string, unknown>;
  switch (ev.event) {
    case "text":
      return { ...draft, text: draft.text + String(d.delta ?? "") };
    case "tool_call":
      return {
        ...draft,
        tool_calls: [
          ...draft.tool_calls,
          { id: String(d.id), name: String(d.name), input: d.input as Record<string, unknown> },
        ],
      };
    case "tool_result":
      return {
        ...draft,
        tool_calls: draft.tool_calls.map((t) =>
          t.id === d.id ? { ...t, ok: Boolean(d.ok), summary: String(d.summary ?? "") } : t,
        ),
      };
    case "ask_user":
      return {
        ...draft,
        ask_user: {
          question: String(d.question ?? ""),
          options: Array.isArray(d.options) ? d.options.map(String) : [],
        },
      };
    case "market_suggestion":
      return { ...draft, market_suggestion: d as unknown as MarketSuggestion };
    case "test_result":
      return { ...draft, test_result: d as unknown as TestResult };
    case "error":
      return {
        ...draft,
        error: {
          message: String(d.message ?? "문제가 생겼어요."),
          hint: d.hint as string | undefined,
        },
      };
    default:
      return draft;
  }
}

export const TOOL_LABEL: Record<string, string> = {
  get_graph: "현재 흐름 확인",
  list_available_nodes: "쓸 수 있는 단계 확인",
  add_node: "단계 추가",
  update_node: "단계 수정",
  remove_node: "단계 삭제",
  connect: "단계 연결",
  get_run: "실행 결과 확인",
  ask_user: "질문하기",
  suggest_market_item: "마켓 추천",
  run_test: "테스트 실행",
  validate: "흐름 검사",
};
