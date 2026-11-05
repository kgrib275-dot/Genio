import type { TraceKind, TraceProvider } from "@/lib/api/trace";
import {
  clampRate,
  isDirty,
  kindOf,
  lastText,
  missingFields,
  newDraft,
  toDraft,
  toPayload,
} from "@/lib/tracingForm";

const OTLP: TraceKind = {
  kind: "otlp",
  label: "OpenTelemetry(OTLP)",
  experimental: false,
  description: "",
  fields: [
    {
      key: "endpoint",
      label: "수집기 주소",
      type: "url",
      required: true,
      default: "",
      hint: "",
      placeholder: "",
    },
    {
      key: "service_name",
      label: "서비스 이름",
      type: "text",
      required: false,
      default: "genio",
      hint: "",
      placeholder: "",
    },
    {
      key: "headers",
      label: "추가 헤더",
      type: "headers",
      required: false,
      default: "",
      hint: "",
      placeholder: "",
    },
  ],
};
const OPIK: TraceKind = {
  kind: "opik",
  label: "Opik(Comet)",
  experimental: true,
  description: "",
  fields: [
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

function saved(over: Partial<TraceProvider> = {}): TraceProvider {
  return {
    id: "ab12cd34",
    kind: "otlp",
    kind_label: "OpenTelemetry(OTLP)",
    experimental: false,
    name: "수집기",
    enabled: true,
    sample_rate: 50,
    only_failed: false,
    fields: { endpoint: "https://o.example.com", service_name: "genio" },
    secrets: {},
    headers: [{ name: "Authorization", masked: "****5555" }],
    ready: true,
    last: null,
    ...over,
  };
}

test("새 서비스는 기본값이 채워진 꺼진 상태", () => {
  const d = newDraft(OTLP);
  expect(d.id).toBe("");
  expect(d.enabled).toBe(false);
  expect(d.sample_rate).toBe(100);
  expect(d.fields.service_name).toBe("genio");
  expect(newDraft(OTLP).uid).not.toBe(d.uid);
});

test("저장된 설정을 편집 값으로 바꾸면 비밀 칸은 비어 있고 헤더는 마스킹만 남는다", () => {
  const d = toDraft(saved());
  expect(d.secrets).toEqual({});
  expect(d.headers).toEqual([{ name: "Authorization", value: "", masked: "****5555" }]);
  expect(isDirty(d, saved())).toBe(false);
});

test("저장 모양: 빈 비밀 칸·빈 헤더 이름은 보내지 않고 표본은 0~100", () => {
  const d = toDraft(saved());
  d.secrets = { api_key: "  ", other: "k-1" };
  d.headers = [
    { name: "Authorization", value: "", masked: "****5555" },
    { name: " ", value: "x", masked: "" },
  ];
  d.sample_rate = 250;
  const p = toPayload(d);
  expect(p.id).toBe("ab12cd34");
  expect(p.secrets).toEqual({ other: "k-1" });
  expect(p.headers).toEqual([{ name: "Authorization", value: "" }]);
  expect(p.sample_rate).toBe(100);
  expect(toPayload(newDraft(OTLP))).not.toHaveProperty("id");
  expect(clampRate(-5)).toBe(0);
  expect(clampRate(Number.NaN)).toBe(100);
});

test("필수 칸 확인: 저장된 키가 있으면 채워진 것으로 본다", () => {
  const d = newDraft(OPIK);
  expect(missingFields(d, OPIK, undefined)).toEqual(["워크스페이스 이름", "API 키"]);
  d.fields.workspace = "ws-1";
  expect(missingFields(d, OPIK, undefined)).toEqual(["API 키"]);
  d.secrets.api_key = "key";
  expect(missingFields(d, OPIK, undefined)).toEqual([]);
  const stored = saved({ kind: "opik", secrets: { api_key: { has: true, masked: "****0000" } } });
  const d2 = { ...newDraft(OPIK), fields: { workspace: "w" } };
  expect(missingFields(d2, OPIK, stored)).toEqual([]);
  expect(missingFields({ ...d2, clear_secrets: ["api_key"] }, OPIK, stored)).toEqual(["API 키"]);
  expect(missingFields(newDraft(OTLP), OTLP, undefined)).toEqual(["수집기 주소"]);
});

test("바꾼 값이 있는지 알아본다", () => {
  const base = saved();
  const d = toDraft(base);
  expect(isDirty(d, base)).toBe(false);
  expect(isDirty({ ...d, enabled: false }, base)).toBe(true);
  expect(isDirty({ ...d, fields: { ...d.fields, endpoint: "https://x" } }, base)).toBe(true);
  expect(isDirty({ ...d, secrets: { api_key: "new" } }, base)).toBe(true);
  expect(
    isDirty({ ...d, headers: [{ name: "Authorization", value: "v", masked: "" }] }, base),
  ).toBe(true);
  expect(isDirty(newDraft(OTLP), undefined)).toBe(true);
});

test("마지막 전송 문장과 서비스 찾기", () => {
  const fmt = () => "11/05 10:00";
  expect(lastText(null, fmt)).toEqual({ tone: "gray", text: "아직 보낸 기록이 없어요" });
  expect(lastText({ at: "x", ok: true, message: "보냈어요." }, fmt)).toEqual({
    tone: "green",
    text: "11/05 10:00 보냄 · 보냈어요.",
  });
  expect(lastText({ at: "x", ok: false, message: "인증 실패" }, fmt).tone).toBe("red");
  expect(kindOf([OTLP, OPIK], "opik")?.label).toBe("Opik(Comet)");
  expect(kindOf([OTLP], "nope")).toBeUndefined();
});
