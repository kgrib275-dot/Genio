import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Logo } from "@/app/Layout";

describe("Logo", () => {
  it("누르면 홈으로 가는 링크다", () => {
    render(
      <MemoryRouter initialEntries={["/knowledge"]}>
        <Logo />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "제니오 홈으로" })).toHaveAttribute("href", "/");
  });
});
