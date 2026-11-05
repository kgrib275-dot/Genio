import { render, screen, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import { ProviderCard } from "@/components/tracing/ProviderCard";
import type { TraceKind, TraceProvider } from "@/lib/api/trace";
import { newDraft, toDraft } from "@/lib/tracingForm";

const KIND: TraceKind = {
  kind: "opik",
  label: "Opik(Comet)",
  experimental: true,
  description: "Comet의 Opik",
  fields: [
    {
      key: "host",
      label: "주소",
      type: "url",
      required: false,
      default: "https://www.comet.com/opik/api",
      hint: "",
      placeholder: "",
    },
    {
      key: "workspace",
      label: "워크스페이스 이름",
      type: "text",
      required: true,
      default: "",
      hint: "",
      placeholder: "",
    },
    {
      key: "api_key",
      label: "API 키",
      type: "secret",
      required: true,
      default: "",
      hint: "",
      placeholder: "",
    },
  ],
};

const SAVED: TraceProvider = {
  id: "p1",
  kind: "opik",
  kind_label: "Opik(Comet)",
  experimental: true,
  name: "Opik",
  enabled: true,
  sample_rate: 100,
  only_failed: false,
  fields: { host: "https://www.comet.com/opik/api", workspace: "w" },
  secrets: { api_key: { has: true, masked: "****0000" } },
  headers: [],
  ready: true,
  last: { at: "2026-11-05T01:00:00Z", ok: false, message: "인증 실패" },
};

test("새 서비스: 실험적 표시, 저장 전 안내, 필수 칸 안내, 시험 버튼 막힘", () => {
  render(
    <ProviderCard
      draft={newDraft(KIND)}
      kind={KIND}
      saved={undefined}
      testing={false}
      onChange={() => {}}
      onRemove={() => {}}
      onTest={async () => ({ ok: true, message: "" })}
    />,
  );
  expect(screen.getByText("실험적")).toBeTruthy();
  expect(screen.getByText("저장 전")).toBeTruthy();
  expect(screen.getByText(/설정 필요/)).toBeTruthy();
  expect((screen.getByRole("button", { name: /연결 시험/ }) as HTMLButtonElement).disabled).toBe(
    true,
  );
  expect(screen.getByText("먼저 저장하면 시험할 수 있어요.")).toBeTruthy();
});

test("저장된 서비스: 저장된 키 표시, 마지막 전송 실패 문장, 시험 결과 보여 주기", async () => {
  const onTest = vi.fn(async () => ({ ok: true, message: "시험 기록을 보냈어요." }));
  const onChange = vi.fn();
  render(
    <ProviderCard
      draft={toDraft(SAVED)}
      kind={KIND}
      saved={SAVED}
      testing={false}
      onChange={onChange}
      onRemove={() => {}}
      onTest={onTest}
    />,
  );
  expect(screen.getByText(/저장됨 \*\*\*\*0000/)).toBeTruthy();
  expect(screen.getByTestId("trace-last-opik").textContent).toContain("실패 · 인증 실패");
  fireEvent.click(screen.getByRole("button", { name: /연결 시험/ }));
  expect(await screen.findByText("시험 기록을 보냈어요.")).toBeTruthy();
  expect(onTest).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("checkbox", { name: /실패한 실행만 보내기/ }));
  expect(onChange.mock.calls[0]?.[0].only_failed).toBe(true);
});
