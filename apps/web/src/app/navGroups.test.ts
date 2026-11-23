import { expect, test } from "vitest";
import { navGroups } from "./nav";

const names = (role: Parameters<typeof navGroups>[0]) =>
  navGroups(role).flatMap((g) => g.items.map((i) => i.label));

test("사용자·운영자는 쓰는 메뉴만 보고 묶음 이름은 붙지 않는다", () => {
  for (const role of ["member", "operator"] as const) {
    expect(names(role)).toEqual(["대시보드", "챗봇 모음", "작업함", "워크스페이스"]);
    expect(navGroups(role).map((g) => g.id)).toEqual(["use", "team"]);
  }
});

test("제작자는 만들기 메뉴가 더해지고 관리는 없다", () => {
  expect(names("builder")).toEqual([
    "대시보드",
    "챗봇 모음",
    "작업함",
    "지식베이스",
    "데이터 표",
    "연결 정보",
    "마켓",
    "워크스페이스",
  ]);
});

test("관리자·소유자는 관리까지 본다", () => {
  for (const role of ["admin", "owner"] as const) {
    expect(names(role)).toContain("관리");
    expect(names(role)).toContain("지식베이스");
  }
});

test("역할을 모르면(로딩 중) 쓰는 메뉴만 보인다", () => {
  expect(names(null)).toEqual(["대시보드", "챗봇 모음", "작업함", "워크스페이스"]);
});
