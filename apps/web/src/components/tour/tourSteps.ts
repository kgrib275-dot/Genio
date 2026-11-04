// v0.6 첫 로그인 화면 투어의 단계(역할별). 화면 요소는 data-tour="..." 로 찾는다.
import type { Role } from "@/lib/api/types";

export interface TourStep {
  id: string;
  /** 짚을 화면 요소(data-tour 값). 화면에 없으면(휴대폰에서 접힌 메뉴 등) 가운데에 안내만 띄운다 */
  target: string;
  title: string;
  body: string;
  roles?: Role[];
}

const EDITORS: Role[] = ["owner", "admin", "builder"];
const MANAGERS: Role[] = ["owner", "admin"];

export const TOUR_STEPS: TourStep[] = [
  {
    id: "composer",
    target: "composer",
    title: "말로 만들기",
    body: '만들고 싶은 것을 여기에 적어요. 예: "고객 문의를 결제와 배송으로 나눠 답하는 챗봇". 빌더가 흐름을 그려 주고, 모르는 건 되물어요.',
    roles: EDITORS,
  },
  {
    id: "apps",
    target: "apps",
    title: "내 앱",
    body: "만든 앱과 쓸 수 있는 앱이 여기에 모여요. 눌러서 열면 시험·배포·기록을 볼 수 있어요.",
  },
  {
    id: "nav",
    target: "nav",
    title: "왼쪽 메뉴",
    body: "작업함(승인·질문), 지식베이스(문서), 데이터 표, 연결 정보, 마켓이 있어요. 아래 '프로젝트'로 앱을 묶어 관리해요.",
  },
  {
    id: "admin-ai",
    target: "nav-admin",
    title: "AI 키부터 등록해요",
    body: "관리 > AI 모델에서 AI 공급자 키를 한 번 등록하면 빌더와 AI 단계가 동작해요. '연결 테스트'로 바로 확인할 수 있어요.",
    roles: MANAGERS,
  },
  {
    id: "learn",
    target: "nav-learn",
    title: "배우기",
    body: "샘플 11가지와 따라 하기 강좌가 있어요. 처음이라면 여기서 30분만 따라 해 보세요.",
  },
  {
    id: "help",
    target: "help-widget",
    title: "막히면 여기",
    body: "어느 화면에서든 이 버튼으로 사용설명서를 찾아보고, 의견이나 문의를 보낼 수 있어요.",
  },
];

/** 역할에 맞는 투어 단계(사용자 역할은 만들기·관리 단계를 빼고 짧게) */
export function stepsFor(role: Role | null): TourStep[] {
  return TOUR_STEPS.filter((s) => !s.roles || (role !== null && s.roles.includes(role)));
}

/** 화면에 보이는 첫 대상(같은 표시가 데스크톱 메뉴·휴대폰 메뉴에 둘 다 있을 수 있다) */
export function findTarget(target: string, root: ParentNode = document): HTMLElement | null {
  const all = root.querySelectorAll<HTMLElement>(`[data-tour="${target}"]`);
  for (const el of all) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return el;
  }
  return null;
}
