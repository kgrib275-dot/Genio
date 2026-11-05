import { fireEvent, render, screen } from "@testing-library/react";
import { ValueInspector } from "@/components/run/ValueInspector";

const steps = [
  { nodeId: "n1", label: "입력", status: "succeeded", output: { name: "김", qty: 5 } },
  {
    nodeId: "n2",
    label: "환율 가져오기",
    status: "succeeded",
    output: { body: { rates: { KRW: 1503.12 }, date: "2026-11-05" }, long: "가".repeat(300) },
  },
  { nodeId: "n3", label: "결과", status: "skipped", output: null },
];

test("단계별 값 목록과 값 끌어오기 경로 복사 단추", () => {
  render(<ValueInspector steps={steps} />);
  expect(screen.getByText("입력")).toBeTruthy();
  expect(screen.getByText("body.rates.KRW")).toBeTruthy();
  expect(screen.getByText("1503.12")).toBeTruthy();
  expect(screen.getByLabelText("body.rates.KRW 값 끌어오기 경로 복사")).toBeTruthy();
  // 값이 없는 단계는 목록에 나오지 않는다
  expect(screen.queryByText("결과")).toBeNull();
});

test("검색하면 맞는 값이 있는 단계만 남고, 긴 값은 줄여 보여 준다", () => {
  render(<ValueInspector steps={steps} />);
  expect(screen.getAllByText("더 보기").length).toBe(1);
  fireEvent.change(screen.getByLabelText("값 찾기"), { target: { value: "krw" } });
  expect(screen.getByText("body.rates.KRW")).toBeTruthy();
  expect(screen.queryByText("name")).toBeNull();
  fireEvent.change(screen.getByLabelText("값 찾기"), { target: { value: "없는말없는말" } });
  expect(screen.getByText("찾는 값이 없어요. 다른 말로 찾아 보세요.")).toBeTruthy();
});

test("값이 하나도 없으면 안내 문장", () => {
  render(<ValueInspector steps={[]} />);
  expect(screen.getByText(/아직 확인할 값이 없어요/)).toBeTruthy();
});
