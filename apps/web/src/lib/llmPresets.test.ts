import { baseUrlToSend, FALLBACK_PRESETS, groupPresets, presetName } from "@/lib/llmPresets";
import type { ProviderPreset } from "@/lib/api/types";

const deepseek: ProviderPreset = {
  key: "deepseek",
  name: "DeepSeek",
  group: "해외",
  base_url: "https://api.deepseek.com/v1",
  default_model: "deepseek-chat",
  models: [{ model: "deepseek-chat", label: "DeepSeek Chat", vision: false, json: true }],
  note: "",
  native: false,
  needs_base_url: false,
  embedding: false,
  vision: false,
};

test("묶음별로 순서를 지켜 정리한다", () => {
  const groups = groupPresets([...FALLBACK_PRESETS, deepseek]);
  expect(groups.map((g) => g.group)).toEqual(["기본", "직접 입력", "해외"]);
  expect(groups[0]?.items.map((p) => p.key)).toEqual(["anthropic", "openai", "google", "azure"]);
});

test("공급자 이름과 보낼 주소", () => {
  expect(presetName([deepseek], "deepseek")).toBe("DeepSeek");
  expect(presetName([deepseek], "unknown")).toBe("unknown");
  // preset 기본 주소와 같으면 보내지 않는다(서버가 기본 주소를 씀)
  expect(baseUrlToSend(deepseek, "https://api.deepseek.com/v1")).toBeUndefined();
  expect(baseUrlToSend(deepseek, " https://proxy.example.com/v1 ")).toBe(
    "https://proxy.example.com/v1",
  );
  expect(baseUrlToSend(deepseek, "")).toBeUndefined();
});
