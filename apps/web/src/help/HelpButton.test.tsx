import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { HelpButton } from "@/help/HelpButton";

describe("HelpButton", () => {
  it("누르면 그 화면의 설명을 팝업으로 보여 준다", () => {
    render(
      <MemoryRouter>
        <HelpButton page="knowledge" />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "이 화면 사용 설명" }));
    const dialog = screen.getByRole("dialog", { name: "도움말 · 지식베이스" });
    expect(dialog).toHaveTextContent("조각 나누기");
    expect(screen.getByRole("link", { name: "전체 설명서 보기" })).toHaveAttribute(
      "href",
      "/help#knowledge",
    );
    fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("공유 화면에서는 전체 설명서 링크를 숨긴다", () => {
    render(
      <MemoryRouter>
        <HelpButton page="share" fullLink={false} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "이 화면 사용 설명" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("공유 챗");
    expect(screen.queryByRole("link", { name: "전체 설명서 보기" })).not.toBeInTheDocument();
  });
});
