import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { EmptyState } from "@/components/EmptyState";
import { checklistItems, newlyDone } from "@/components/onboarding/checklist";
import { findTarget, stepsFor } from "@/components/tour/tourSteps";
import type { OnboardingStatus } from "@/lib/api/onboarding";
import { searchHelp } from "@/lib/helpEvents";

const NONE: OnboardingStatus = {
  ai_connected: false,
  samples_installed: false,
  app_created: false,
  test_run: false,
  version_saved: false,
  deployed: false,
  team_invited: false,
};

test("화면 투어 단계는 역할에 맞게 고른다", () => {
  const owner = stepsFor("owner").map((s) => s.id);
  expect(owner).toEqual(["composer", "apps", "nav", "admin-ai", "learn", "help"]);
  const builder = stepsFor("builder").map((s) => s.id);
  expect(builder).not.toContain("admin-ai");
  expect(builder).toContain("composer");
  const member = stepsFor("member").map((s) => s.id);
  expect(member).toEqual(["apps", "nav", "learn", "help"]);
  expect(stepsFor(null).every((s) => !s.roles)).toBe(true);
});

test("보이는 대상만 짚는다(없으면 null)", () => {
  document.body.innerHTML =
    '<div data-tour="nav" id="hidden"></div><div data-tour="nav" id="shown"></div>';
  const shown = document.getElementById("shown") as HTMLElement;
  shown.getBoundingClientRect = () =>
    ({ width: 100, height: 30, top: 0, left: 0, right: 100, bottom: 30, x: 0, y: 0 }) as DOMRect;
  expect(findTarget("nav")?.id).toBe("shown");
  expect(findTarget("nothing")).toBeNull();
  document.body.innerHTML = "";
});

test("시작 체크리스트: 역할별 항목과 실제 데이터·내 기록으로 끝남 판단", () => {
  expect(checklistItems("member", NONE)).toEqual([]);
  const owner = checklistItems("owner", { ...NONE, ai_connected: true, deployed: true });
  expect(owner.map((i) => i.key)).toEqual(["ai", "samples", "app", "test", "deploy", "team"]);
  expect(owner.filter((i) => i.done).map((i) => i.key)).toEqual(["ai", "deploy"]);
  const builder = checklistItems("builder", NONE, ["app"]);
  expect(builder.map((i) => i.key)).not.toContain("ai");
  expect(builder.find((i) => i.key === "app")?.done).toBe(true);
  expect(newlyDone(owner, ["ai"])).toEqual(["deploy"]);
});

test("빈 화면 안내: 제목·설명·다음 행동 버튼", () => {
  const onClick = vi.fn();
  render(
    <MemoryRouter>
      <EmptyState
        title="아직 앱이 없어요"
        description="말로 만들어 보세요"
        action={{ label: "말로 만들기", onClick }}
        secondary={{ label: "샘플로 배우기", to: "/learn" }}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText("아직 앱이 없어요")).toBeInTheDocument();
  expect(screen.getByText("말로 만들어 보세요")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "말로 만들기" }));
  expect(onClick).toHaveBeenCalled();
  expect(screen.getByRole("link", { name: "샘플로 배우기" })).toHaveAttribute("href", "/learn");
});

test("도움말 찾기는 낱말이 모두 들어간 단락만", () => {
  expect(searchHelp("").length).toBeGreaterThan(10);
  const r = searchHelp("병렬 갈래");
  expect(r.length).toBeGreaterThan(0);
  expect(r.map((s) => s.id)).toContain("parallel");
  expect(searchHelp("없는낱말xyz")).toEqual([]);
});
