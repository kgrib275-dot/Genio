import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { ChainEditor } from "@/components/llm/ChainEditor";
import { LlmKeysPanel } from "@/components/llm/LlmKeysPanel";
import type { LlmProvider } from "@/lib/api/types";
import { DEFAULT_TRIGGERS, type ChainLink } from "@/lib/llmChain";

const CONNS = [
  { id: "a", label: "메인 GPT", provider: "openai", default_model: "gpt-4o-mini" },
  { id: "b", label: "대체 Claude", provider: "anthropic", default_model: "claude-sonnet-5-5" },
  { id: "c", label: "구글", provider: "google", default_model: "gemini-2.5-flash" },
];

function Harness({ initial }: { initial: ChainLink[] }) {
  const [links, setLinks] = useState(initial);
  const [triggers, setTriggers] = useState(DEFAULT_TRIGGERS);
  return (
    <>
      <ChainEditor
        connections={CONNS}
        links={links}
        triggers={triggers}
        onLinks={setLinks}
        onTriggers={setTriggers}
      />
      <output data-testid="order">{links.map((l) => l.provider_id).join(",")}</output>
      <output data-testid="triggers">
        {Object.entries(triggers)
          .filter(([, v]) => v)
          .map(([k]) => k)
          .join(",")}
      </output>
    </>
  );
}

test("순서 편집기: 추가·위아래·빼기와 조건 체크", () => {
  render(<Harness initial={[{ provider_id: "b", model: "" }]} />);
  expect(screen.getByTestId("order").textContent).toBe("b");
  // 이미 고른 연결은 목록에서 빠진다
  const select = screen.getByLabelText("대체 연결 고르기") as HTMLSelectElement;
  expect(Array.from(select.options).map((o) => o.value)).toEqual(["", "a", "c"]);
  fireEvent.change(select, { target: { value: "c" } });
  fireEvent.click(screen.getByRole("button", { name: "추가" }));
  expect(screen.getByTestId("order").textContent).toBe("b,c");
  fireEvent.click(screen.getByRole("button", { name: "구글 위로" }));
  expect(screen.getByTestId("order").textContent).toBe("c,b");
  // 첫 줄의 위로·마지막 줄의 아래로는 눌 수 없다
  expect((screen.getByRole("button", { name: "구글 위로" }) as HTMLButtonElement).disabled).toBe(
    true,
  );
  expect(
    (screen.getByRole("button", { name: "대체 Claude 아래로" }) as HTMLButtonElement).disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "구글 빼기" }));
  expect(screen.getByTestId("order").textContent).toBe("b");
  // 조건 체크
  expect(screen.getByTestId("triggers").textContent).toBe("outage,rate_limit");
  fireEvent.click(screen.getByLabelText(/안전 정책으로 답하지 않음/));
  expect(screen.getByTestId("triggers").textContent).toBe("outage,rate_limit,content_filter");
});

test("순서 편집기: 읽기 전용이면 바꾸는 버튼이 없다", () => {
  render(
    <ChainEditor
      connections={CONNS}
      links={[{ provider_id: "a", model: "" }]}
      triggers={DEFAULT_TRIGGERS}
      onLinks={() => undefined}
      onTriggers={() => undefined}
      readOnly
    />,
  );
  expect(screen.queryByRole("button", { name: "추가" })).toBeNull();
  expect(screen.queryByLabelText("메인 GPT 빼기")).toBeNull();
});

function withClient(ui: React.ReactElement) {
  return <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>;
}

const PROVIDER = {
  id: "p1",
  provider: "openai",
  label: "메인",
  base_url: null,
  default_model: "gpt-4o-mini",
  is_default: true,
  api_key_masked: "****0001",
  key_strategy: "weighted",
  keys: [
    {
      id: "primary",
      label: "기본 키",
      masked: "****0001",
      weight: 3,
      disabled: false,
      primary: true,
      position: 1,
      calls: 5,
      errors: 1,
      last_error: "한도 초과",
      cooldown_seconds: 75,
    },
    {
      id: "k2",
      label: "팀 B 키",
      masked: "****0002",
      weight: 1,
      disabled: true,
      primary: false,
      position: 2,
      calls: 0,
      errors: 0,
      last_error: "",
      cooldown_seconds: 0,
    },
  ],
} as unknown as LlmProvider;

test("키 관리: 펼치면 키 목록·쉬는 시간·꺼 둔 표시, 기본 키는 끄거나 지울 수 없다", () => {
  render(withClient(<LlmKeysPanel ws="w1" provider={PROVIDER} manage />));
  const toggle = screen.getByRole("button", { name: /키 2개/ });
  expect(toggle.textContent).toContain("비중대로");
  expect(screen.queryByText("팀 B 키")).toBeNull();
  fireEvent.click(toggle);
  expect(screen.getByText("팀 B 키")).toBeTruthy();
  expect(screen.getByText("****0002")).toBeTruthy();
  expect(screen.getByText(/쉬는 중 1분 15초/)).toBeTruthy();
  expect(screen.getByText("꺼 둠")).toBeTruthy();
  expect(screen.getByText(/마지막 오류: 한도 초과/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: "기본 키 끄기" })).toBeNull();
  expect(screen.queryByRole("button", { name: "기본 키 지우기" })).toBeNull();
  expect(screen.getByRole("button", { name: "팀 B 키 켜기" })).toBeTruthy();
  // 비중 칸은 '비중대로'일 때만 보인다
  expect(screen.getByLabelText("기본 키 비중")).toBeTruthy();
});

test("키 관리: 읽기 전용이면 키 더하기 칸이 없다", () => {
  render(withClient(<LlmKeysPanel ws="w1" provider={PROVIDER} manage={false} />));
  fireEvent.click(screen.getByRole("button", { name: /키 2개/ }));
  expect(screen.queryByLabelText("새 키 값")).toBeNull();
  expect(screen.queryByRole("button", { name: "팀 B 키 켜기" })).toBeNull();
});
