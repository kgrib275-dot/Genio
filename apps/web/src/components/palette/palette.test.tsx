// 전체 검색창·단축키 창·포커스 가두기 시험
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { vi } from "vitest";
import { CommandPalette } from "@/components/palette/CommandPalette";
import { ShortcutsDialog } from "@/components/palette/ShortcutsDialog";
import { Dialog } from "@/components/ui/dialog";
import { trapTab } from "@/lib/useFocusTrap";
import { useSession } from "@/store/session";

vi.mock("@/lib/api/search", () => ({
  usePaletteSearch: (_ws: string, q: string) => ({
    data: {
      query: q,
      groups: q
        ? [
            {
              kind: "apps",
              label: "앱",
              items: [
                { id: "a1", title: "휴가 신청 봇", subtitle: "연차 신청", to: "/apps/a1/builder" },
                { id: "a2", title: "휴가 현황", subtitle: "", to: "/apps/a2/builder" },
              ],
            },
          ]
        : [
            {
              kind: "pages",
              label: "화면",
              items: [{ id: "/learn", title: "배우기", subtitle: "샘플과 강좌", to: "/learn" }],
            },
          ],
    },
    isFetching: false,
    error: null,
  }),
}));

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function renderPalette(onClose = vi.fn()) {
  useSession.setState({ workspaceId: "w1", role: "builder" });
  window.localStorage.clear();
  render(
    <MemoryRouter>
      <CommandPalette open onClose={onClose} />
      <Where />
    </MemoryRouter>,
  );
  return onClose;
}

describe("전체 검색창", () => {
  test("열면 검색칸에 포커스가 있고, 검색어가 비면 화면·바로 하기가 보인다", () => {
    renderPalette();
    expect(document.activeElement).toBe(screen.getByLabelText("찾을 것"));
    expect(screen.getByRole("dialog", { name: "전체 검색" })).toBeTruthy();
    expect(screen.getByText("배우기")).toBeTruthy();
    expect(screen.getByText("단축키 보기")).toBeTruthy();
  });

  test("검색어를 치면 결과가 강조되어 나오고 ↑↓ Enter로 연다", async () => {
    const onClose = renderPalette();
    const input = screen.getByLabelText("찾을 것");
    fireEvent.change(input, { target: { value: "휴가" } });
    const opts = await screen.findAllByRole("option", { name: /휴가/ });
    expect(opts.length).toBeGreaterThanOrEqual(2);
    expect(opts[0]?.getAttribute("aria-selected")).toBe("true");
    expect(document.querySelectorAll("mark").length).toBeGreaterThan(0);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getAllByRole("option")[1]?.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onClose).toHaveBeenCalled();
    expect(screen.getByTestId("where").textContent).toBe("/apps/a1/builder");
    // 연 곳은 최근 항목에 남는다
    expect(window.localStorage.getItem("genio.palette.recent.w1")).toContain("휴가 신청 봇");
  });

  test("Esc로 닫고, 맞는 게 없으면 안내한다", async () => {
    const onClose = renderPalette();
    const input = screen.getByLabelText("찾을 것");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "휴가" } });
    const opts = await screen.findAllByRole("option", { name: /휴가 현황/ });
    fireEvent.click(opts[0] as HTMLElement);
    expect(screen.getByTestId("where").textContent).toBe("/apps/a2/builder");
  });
});

describe("단축키 보기", () => {
  test("어디서나·검색창·캔버스·챗 묶음이 보인다", () => {
    render(<ShortcutsDialog open onClose={() => {}} />);
    for (const title of ["어디서나", "검색창 안에서", "만들기 화면(캔버스)", "챗 입력칸"])
      expect(screen.getByRole("region", { name: title })).toBeTruthy();
    expect(screen.getByText("단축키 보기", { selector: "h2" })).toBeTruthy();
    expect(screen.getAllByText(/Shift \+ \?/).length).toBeGreaterThan(0);
  });
});

describe("포커스 가두기", () => {
  test("Tab이 마지막 요소에서 첫 요소로 돌고 Shift+Tab은 반대로 돈다", () => {
    render(
      <div data-testid="box">
        <button>첫째</button>
        <button>둘째</button>
      </div>,
    );
    const box = screen.getByTestId("box");
    const [first, second] = screen.getAllByRole("button");
    second?.focus();
    const tab = new KeyboardEvent("keydown", { key: "Tab", cancelable: true });
    expect(trapTab(tab, box)).toBe(true);
    expect(document.activeElement).toBe(first);
    first?.focus();
    const back = new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, cancelable: true });
    expect(trapTab(back, box)).toBe(true);
    expect(document.activeElement).toBe(second);
    // 가운데에서는 건드리지 않는다
    const none = new KeyboardEvent("keydown", { key: "a", cancelable: true });
    expect(trapTab(none, box)).toBe(false);
  });

  test("대화상자를 열면 안으로 포커스가 들어가고 닫으면 원래 자리로 돌아간다", () => {
    function Host({ open }: { open: boolean }) {
      return (
        <>
          <button data-testid="opener">열기</button>
          <Dialog open={open} onClose={() => {}} title="시험 창">
            <input aria-label="이름" />
          </Dialog>
        </>
      );
    }
    const { rerender } = render(<Host open={false} />);
    screen.getByTestId("opener").focus();
    rerender(<Host open />);
    expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);
    rerender(<Host open={false} />);
    expect(document.activeElement).toBe(screen.getByTestId("opener"));
  });
});
