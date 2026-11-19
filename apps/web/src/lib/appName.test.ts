import { appDescriptionFrom, appNameFrom } from "@/lib/appName";

describe("appNameFrom", () => {
  it("부탁 끝말과 조사를 떼고 이름으로 만든다", () => {
    expect(appNameFrom("고객 문의를 분류해서 답하는 챗봇을 만들어 줘")).toBe(
      "고객 문의를 분류해서 답하는 챗봇",
    );
    expect(appNameFrom("회의 메모를 받아 할 일 목록으로 정리해 줘")).toBe(
      "회의 메모를 받아 할 일 목록으로 정리",
    );
    expect(appNameFrom("  메일 요약 앱 만들어줘.  ")).toBe("메일 요약 앱");
  });

  it("길면 띄어쓰기에서 자르고 …을 붙인다", () => {
    const name = appNameFrom("주간 보고 초안을 만들어서 승인 후 메일로 보내는 아주 긴 이름의 앱");
    expect(name.endsWith("…")).toBe(true);
    expect(name.length).toBeLessThanOrEqual(25);
    expect(name.slice(0, -1).endsWith(" ")).toBe(false);
  });

  it("비면 새 앱", () => {
    expect(appNameFrom("   ")).toBe("새 앱");
  });
});

describe("appDescriptionFrom", () => {
  it("부탁 끝말을 뗀 한 줄을 설명으로 쓴다", () => {
    expect(appDescriptionFrom("사내 휴가 규정 문서로 직원 질문에 답하는 챗봇을 만들어 줘")).toBe(
      "사내 휴가 규정 문서로 직원 질문에 답하는 챗봇",
    );
  });
  it("너무 길면 120자에서 줄인다", () => {
    expect(appDescriptionFrom("가".repeat(200)).length).toBe(121);
  });
});
