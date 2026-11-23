import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, expect, test } from "vitest";
import { GUIDES, guideById, guidesFor } from "@/lib/guides";
import { useGuide } from "@/store/guide";
import { useSession } from "@/store/session";
import { GuideDock } from "./GuideDock";
import { GuidedStart } from "./GuidedStart";

function Where() {
  const l = useLocation();
  return <p data-testid="where">{l.pathname + l.search}</p>;
}

function renderBoth() {
  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <GuidedStart />
              <GuideDock />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  useGuide.setState({ active: null });
  useSession.setState({ role: "builder" });
});

test("가이드 내용: 모든 단계에 제목과 설명이 있고 이동 주소가 올바르다", () => {
  expect(GUIDES.length).toBeGreaterThanOrEqual(6);
  for (const g of GUIDES) {
    expect(g.steps.length).toBeGreaterThanOrEqual(3);
    for (const s of g.steps) {
      expect(s.title.length).toBeGreaterThan(0);
      expect(s.body.length).toBeGreaterThan(5);
      if (s.action) expect(s.action.to.startsWith("/")).toBe(true);
    }
  }
});

test("만드는 사람과 쓰는 사람에게 다른 가이드가 보인다", () => {
  expect(guidesFor("builder").map((g) => g.id)).toEqual(["docs", "auto", "approval", "connect"]);
  expect(guidesFor("owner").length).toBe(4);
  for (const role of ["member", "operator"] as const) {
    expect(guidesFor(role).map((g) => g.id)).toEqual(["chat", "tasks"]);
  }
  expect(guidesFor(null)).toEqual([]);
});

test("목표를 고르면 첫 단계 화면으로 가고 안내 창이 따라온다", () => {
  renderBoth();
  fireEvent.click(screen.getByRole("button", { name: /내 문서로 답하는 챗봇/ }));
  expect(screen.getByTestId("where").textContent).toBe("/knowledge");
  const dock = screen.getByRole("region", { name: /가이드: 내 문서로 답하는 챗봇/ });
  expect(dock).toHaveTextContent("1/4단계");
  expect(dock).toHaveTextContent("문서 올리기");
});

test("다음·이전으로 옮기고, 끝내면 축하 안내가 뜬다", () => {
  useGuide.getState().start("tasks");
  renderBoth();
  const next = () => fireEvent.click(screen.getByRole("button", { name: /했어요, 다음/ }));
  next();
  expect(screen.getByRole("region", { name: /가이드/ })).toHaveTextContent("2/3단계");
  fireEvent.click(screen.getByRole("button", { name: /이전/ }));
  expect(screen.getByRole("region", { name: /가이드/ })).toHaveTextContent("1/3단계");
  next();
  next();
  fireEvent.click(screen.getByRole("button", { name: /끝냈어요/ }));
  expect(screen.getByRole("status", { name: "가이드 끝" })).toBeInTheDocument();
  expect(useGuide.getState().active).toBeNull();
});

test("그만두기를 누르면 안내 창이 사라지고 기억도 지운다", () => {
  useGuide.getState().start("docs");
  renderBoth();
  fireEvent.click(screen.getByRole("button", { name: "가이드 그만두기" }));
  expect(screen.queryByRole("region", { name: /가이드: / })).not.toBeInTheDocument();
  expect(window.localStorage.getItem("genio.guide")).toBeNull();
});

test("진행 상태는 저장되고, 망가진 저장값은 무시한다", () => {
  useGuide.getState().start("auto");
  useGuide.getState().go(2);
  expect(JSON.parse(window.localStorage.getItem("genio.guide") ?? "{}")).toEqual({
    id: "auto",
    step: 2,
  });
  useGuide.getState().go(99); // 범위 밖은 무시
  expect(useGuide.getState().active?.step).toBe(2);
  expect(guideById("없는가이드")).toBeUndefined();
  useGuide.getState().start("없는가이드");
  expect(useGuide.getState().active?.id).toBe("auto");
});

test("사용자에게는 쓰기 안내만 보인다", () => {
  useSession.setState({ role: "member" });
  renderBoth();
  expect(screen.getByRole("button", { name: /챗봇에게 물어보기/ })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /내 문서로 답하는 챗봇/ })).not.toBeInTheDocument();
});
