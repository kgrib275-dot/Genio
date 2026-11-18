import { fireEvent, render, screen } from "@testing-library/react";
import { PinSettings } from "@/components/canvas/FailureSettings";

describe("PinSettings", () => {
  it("고정한 값이 없으면 아무것도 보이지 않는다", () => {
    const { container } = render(<PinSettings data={{ label: "계산" }} onChange={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("고정한 값이 있으면 안내가 보이고, 고정 해제는 _pinned만 지운다", () => {
    const seen: Record<string, unknown>[] = [];
    render(
      <PinSettings
        data={{ label: "계산", _pinned: { output: { n: 99, text: "x" } } }}
        onChange={(d) => seen.push(d)}
      />,
    );
    expect(screen.getByText(/고정한 값을 써요/)).toBeInTheDocument();
    expect(screen.getByText(/n, text/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "고정 해제" }));
    expect(seen).toEqual([{ label: "계산" }]);
  });

  it("읽기 전용이면 해제 버튼이 없다", () => {
    render(<PinSettings data={{ _pinned: { output: { a: 1 } } }} onChange={() => {}} readOnly />);
    expect(screen.queryByRole("button", { name: "고정 해제" })).toBeNull();
  });
});
