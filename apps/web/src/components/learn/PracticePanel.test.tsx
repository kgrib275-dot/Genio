import { fireEvent, render, screen } from "@testing-library/react";
import { PracticePanel } from "@/components/learn/PracticePanel";
import { LESSONS } from "@/help/learn";

const lesson = LESSONS[0] ?? { id: "x", steps: [] as string[] };

beforeEach(() => window.localStorage.clear());

describe("PracticePanel", () => {
  it("지금 할 일을 알려 주고, 체크하면 다음 단계로 넘어가며 진행이 기억된다", () => {
    const { unmount } = render(<PracticePanel lessonId={lesson.id} onClose={() => undefined} />);
    expect(screen.getByText(`0/${lesson.steps.length}`)).toBeInTheDocument();
    expect(screen.getByText(/지금 할 일은/)).toHaveTextContent("1번");
    fireEvent.click(screen.getAllByRole("button", { pressed: false })[0] as HTMLElement);
    expect(screen.getByText(`1/${lesson.steps.length}`)).toBeInTheDocument();
    expect(screen.getByText(/지금 할 일은/)).toHaveTextContent("2번");
    unmount();
    render(<PracticePanel lessonId={lesson.id} onClose={() => undefined} />);
    expect(screen.getByText(`1/${lesson.steps.length}`)).toBeInTheDocument();
  });

  it("모르는 강좌 번호면 아무것도 그리지 않고, 끝내기를 누르면 닫힌다", () => {
    const { container } = render(<PracticePanel lessonId="nope" onClose={() => undefined} />);
    expect(container).toBeEmptyDOMElement();
    const onClose = vi.fn();
    render(<PracticePanel lessonId={lesson.id} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "실습 끝내기" }));
    expect(onClose).toHaveBeenCalled();
  });
});
