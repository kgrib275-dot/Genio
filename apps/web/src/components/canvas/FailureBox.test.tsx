import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { FailureBox } from "@/components/canvas/RunPanel";
import { fixRequestMessage } from "@/lib/api/v5c";

function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.pathname + loc.search}</div>;
}

function renderBox(diagnosis: Parameters<typeof FailureBox>[0]["run"]["diagnosis"]) {
  return render(
    <MemoryRouter initialEntries={["/run"]}>
      <Routes>
        <Route
          path="/run"
          element={
            <FailureBox
              run={{ id: "r1", error: null, diagnosis }}
              steps={[
                {
                  node_id: "n1",
                  label: "주문 조회",
                  status: "failed",
                  summary: "서버가 401을 돌려줬어요.\n연결 정보를 확인하세요.",
                } as never,
              ]}
              appId="a1"
            />
          }
        />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("FailureBox 자동 진단 제안", () => {
  it("제안 버튼을 누르면 그 문장을 붙여 빌더로 간다", () => {
    renderBox({
      node_id: "n1",
      node_label: "주문 조회",
      node_type: "http",
      suggestions: [
        { id: "auth", label: "연결 정보 다시 고르기", prompt: "연결 정보를 다시 골라 줘" },
        { id: "generic", label: "원인을 찾아 고치기", prompt: "원인을 찾아 줘" },
      ],
    });
    expect(screen.getByText("이렇게 고칠까요?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "연결 정보 다시 고르기" }));
    const where = screen.getByTestId("where").textContent ?? "";
    expect(where.startsWith("/apps/a1/builder?fix=r1&hint=")).toBe(true);
    expect(decodeURIComponent(where)).toContain("연결 정보를 다시 골라 줘");
  });

  it("제안이 없으면 기존 버튼만 보인다", () => {
    renderBox(null);
    expect(screen.queryByTestId("fix-suggestions")).toBeNull();
    expect(screen.getByRole("button", { name: /빌더에게 고쳐 달라고 하기/ })).toBeInTheDocument();
  });

  it("고쳐 달라는 문장에 제안을 덧붙인다", () => {
    expect(fixRequestMessage("r1")).toBe("이 실행이 왜 실패했는지 보고 고쳐 줘 (실행 r1)");
    expect(fixRequestMessage("r1", "제한 시간을 늘려 줘")).toContain("제한 시간을 늘려 줘");
  });
});
