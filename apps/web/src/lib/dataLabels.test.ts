import { humanizeRefs } from "@/lib/dataLabels";

describe("humanizeRefs", () => {
  it("값 끌어오기를 사람 말로 바꾼다", () => {
    expect(humanizeRefs("질문: {{n1.message}} 자료: {{ n2.context }}")).toMatch(
      /질문: 「.+」 자료: 「.+」/,
    );
    expect(humanizeRefs("그냥 글")).toBe("그냥 글");
  });
});
