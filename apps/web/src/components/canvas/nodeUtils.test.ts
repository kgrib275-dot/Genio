import {
  branchHandles,
  conditionHandles,
  defaultData,
  hasFailHandle,
} from "@/components/canvas/nodeUtils";

describe("단계 출구 핸들", () => {
  it("질문 분류는 분류 id마다 출구를 만든다(이름은 표시용)", () => {
    const h = branchHandles("question_classifier", {
      classes: [{ id: "billing", name: "결제" }, { id: "tech", name: "" }, { name: "id 없음" }],
    });
    expect(h).toEqual([
      { id: "billing", label: "결제" },
      { id: "tech", label: "tech" },
    ]);
  });

  it("조건 분기는 case id + 나머지 출구", () => {
    expect(conditionHandles({ cases: [{ id: "c1" }], else: "other" })).toEqual(["c1", "other"]);
    expect(branchHandles("condition", { cases: [{ id: "c1" }] }).map((x) => x.id)).toEqual([
      "c1",
      "else",
    ]);
  });

  it("일반 단계는 분기 출구가 없고, 실패 분기를 켜면 fail 출구가 생긴다", () => {
    expect(branchHandles("llm", { _on_error: "branch" })).toEqual([]);
    expect(hasFailHandle({ _on_error: "branch" })).toBe(true);
    expect(hasFailHandle({ _on_error: "default" })).toBe(false);
    expect(hasFailHandle({})).toBe(false);
  });

  it("새 질문 분류 단계는 분류 두 개로 시작한다", () => {
    const data = defaultData({
      type: "question_classifier",
      label: "질문 분류",
      category: "AI",
      description: "",
      input_schema: { type: "object", properties: {} },
      output_schema: {},
      ui_schema: {},
      source: "builtin",
    });
    expect((data.classes as unknown[]).length).toBe(2);
  });
});
