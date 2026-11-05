import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SourcesCard } from "@/pages/knowledge/KbSourcesPanel";
import { TuningCard } from "@/pages/knowledge/KbTuning";
import { UsageBar } from "@/pages/knowledge/KbUsage";

const SOURCES = [
  {
    id: "s1",
    type: "web",
    name: "제품 설명서",
    config: { url: "https://docs.example.com/", depth: 1, max_pages: 20 },
    schedule: "daily",
    created_at: "2026-11-05T00:00:00Z",
    last_sync_at: "2026-11-05T01:00:00Z",
    last_status: "partial",
    last_summary: {
      added: 3,
      updated: 1,
      unchanged: 2,
      missing: 0,
      failed: 1,
      notes: ["robots.txt가 막은 쪽 1개는 건너뛰었어요."],
      failures: ["https://docs.example.com/x — 주소가 열리지 않아요(404)."],
    },
    last_error: null,
    running: false,
    running_since: null,
    progress: null,
  },
  {
    id: "s2",
    type: "notion",
    name: "사내 위키",
    config: { targets: ["a", "b"] },
    schedule: "none",
    created_at: "2026-11-05T00:00:00Z",
    last_sync_at: null,
    last_status: "new",
    last_summary: null,
    last_error: null,
    running: true,
    running_since: "2026-11-05T02:00:00Z",
    progress: { done: 4, total: 10 },
  },
];

const TUNING = {
  questions: [
    { id: "q1", question: "연차는 며칠인가요?", expect_keyword: "15일", expect_document_id: "" },
  ],
  last_run: {
    at: "2026-11-05T03:00:00Z",
    questions: 1,
    include_rerank: false,
    threshold: 0,
    rows: [
      {
        method: "vector",
        top_k: 3,
        rerank: false,
        hit_rate: 0.5,
        hits: 0,
        avg_top_score: 0.4,
        avg_ms: 12,
      },
      {
        method: "hybrid",
        top_k: 5,
        rerank: false,
        hit_rate: 1,
        hits: 1,
        avg_top_score: 0.7,
        avg_ms: 20,
        is_best: true,
      },
    ],
    best: {
      method: "hybrid",
      top_k: 5,
      rerank: false,
      hit_rate: 1,
      hits: 1,
      avg_top_score: 0.7,
      avg_ms: 20,
    },
    current_row: {
      method: "vector",
      top_k: 4,
      rerank: false,
      hit_rate: 0.5,
      hits: 0,
      avg_top_score: 0.4,
      avg_ms: 12,
      is_current: true,
    },
    suggested_threshold: 0.45,
    errors: {},
    truncated: false,
  },
  estimate: {
    questions: 1,
    combos: 9,
    searches: 3,
    embedding_calls: 2,
    with_rerank: { combos: 12, searches: 6, embedding_calls: 4, rerank_llm_calls: 3 },
  },
  current: { method: "vector", top_k: 4, score_threshold: 0, rerank: false },
  max_questions: 30,
};

const USAGE = {
  usage: { documents: 1800, bytes: 3 * 1024 * 1024 },
  limits: { max_documents: 2000, max_total_mb: 0, max_writes_per_min: 120 },
  can_edit: true,
  labels: {
    max_documents: "문서 수",
    max_total_mb: "전체 크기(MB)",
    max_writes_per_min: "분당 올리기 횟수",
  },
};

vi.mock("@/lib/api/client", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      get: (path: string) => {
        if (path.includes("/sources")) return Promise.resolve(SOURCES);
        if (path.includes("/tuning")) return Promise.resolve(TUNING);
        if (path.includes("/knowledge/usage")) return Promise.resolve(USAGE);
        return Promise.resolve([]);
      },
    },
  };
});

function wrap(ui: React.ReactElement) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

test("가져오기 소스: 상태·진행·결과·실패 목록", async () => {
  wrap(<SourcesCard ws="w1" kbId="k1" editable adding={null} onCloseAdd={() => undefined} />);
  expect(await screen.findByText("제품 설명서")).toBeInTheDocument();
  expect(screen.getByText("일부만 가져옴")).toBeInTheDocument();
  expect(screen.getByText("매일")).toBeInTheDocument();
  expect(screen.getByText(/새 3 · 바뀜 1 · 그대로 2 · 실패 1/)).toBeInTheDocument();
  expect(screen.getByText(/robots\.txt가 막은 쪽 1개/)).toBeInTheDocument();
  expect(screen.getByText("가져오는 중 4/10")).toBeInTheDocument();
  const bar = screen.getByRole("progressbar", { name: "가져오기 진행" });
  expect(bar).toHaveAttribute("aria-valuenow", "4");
  // 가져오는 중인 소스는 '지금 가져오기'를 누를 수 없다
  expect(screen.getByRole("button", { name: "사내 위키 지금 가져오기" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "제품 설명서 지금 가져오기" })).toBeEnabled();
});

test("가져오기 소스: 읽기 전용이면 동작 버튼이 없다", async () => {
  wrap(
    <SourcesCard ws="w1" kbId="k1" editable={false} adding={null} onCloseAdd={() => undefined} />,
  );
  expect(await screen.findByText("제품 설명서")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /지금 가져오기/ })).toBeNull();
});

test("웹사이트 추가 대화상자: 주소를 넣어야 가져올 수 있다", async () => {
  wrap(<SourcesCard ws="w1" kbId="k1" editable adding="web" onCloseAdd={() => undefined} />);
  const dialog = await screen.findByRole("dialog", { name: "웹사이트 가져오기" });
  const go = screen.getByRole("button", { name: /가져오기$/ });
  expect(go).toBeDisabled();
  fireEvent.change(screen.getByLabelText("시작 주소"), {
    target: { value: "https://docs.example.com/" },
  });
  await waitFor(() => expect(go).toBeEnabled());
  expect(dialog).toHaveTextContent("robots.txt");
});

test("Notion 추가 대화상자: 연결 정보가 없으면 안내한다", async () => {
  wrap(<SourcesCard ws="w1" kbId="k1" editable adding="notion" onCloseAdd={() => undefined} />);
  expect(await screen.findByRole("dialog", { name: "Notion 가져오기" })).toBeInTheDocument();
  expect(await screen.findByText(/노션 연결 정보가 아직 없어요/)).toBeInTheDocument();
});

test("사용량 막대: 임박하면 빨갛게, 한도 0은 제한 없음", async () => {
  wrap(<UsageBar ws="w1" />);
  expect(await screen.findByText("1,800개 / 2,000개")).toBeInTheDocument();
  expect(screen.getByText(/3\.0MB.*제한 없음|제한 없음/)).toBeInTheDocument();
  expect(screen.getByRole("progressbar", { name: "문서 사용량" })).toHaveAttribute(
    "aria-valuenow",
    "90",
  );
  fireEvent.click(screen.getByRole("button", { name: /한도 바꾸기/ }));
  expect(await screen.findByRole("dialog", { name: "지식 사용 한도" })).toBeInTheDocument();
});

test("검색 튜닝: 가장 좋은 설정·지금 설정·적용 버튼", async () => {
  wrap(<TuningCard kbId="k1" docs={[]} editable />);
  expect(await screen.findByText(/가장 좋은 설정: 혼합 · 5개/)).toBeInTheDocument();
  expect(screen.getByText(/지금 설정보다 적중률이 50%p 높아요/)).toBeInTheDocument();
  expect(screen.getByText(/점수 기준은 0\.45/)).toBeInTheDocument();
  expect(screen.getByText("지금 설정")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "이 설정으로 적용" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "혼합 · 5개 적용" })).toBeInTheDocument();
  // 재정렬은 비용 확인 전에는 실행할 수 없다
  const run = screen.getByRole("button", { name: /튜닝 실행/ });
  expect(run).toBeEnabled();
  fireEvent.click(screen.getByLabelText("다시 순위 매기기(재정렬)도 비교"));
  expect(run).toBeDisabled();
  expect(screen.getByText(/AI를 질문마다 한 번씩 더 불러요/)).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("비용을 알고 실행할게요"));
  expect(run).toBeEnabled();
});

test("검색 튜닝: 읽기 전용이면 적용·실행이 없다", async () => {
  wrap(<TuningCard kbId="k1" docs={[]} editable={false} />);
  expect(await screen.findByText(/가장 좋은 설정: 혼합 · 5개/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /튜닝 실행/ })).toBeNull();
  expect(screen.queryByRole("button", { name: "혼합 · 5개 적용" })).toBeNull();
});
