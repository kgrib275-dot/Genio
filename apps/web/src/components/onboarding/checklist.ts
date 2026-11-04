// v0.6 시작 체크리스트 항목(역할별). 실제 데이터(서버 상태)와 내 기록(steps_done)으로 끝남을 판단한다.
import type { OnboardingStatus } from "@/lib/api/onboarding";
import type { Role } from "@/lib/api/types";

export type ChecklistKey = "ai" | "samples" | "app" | "test" | "deploy" | "team";

export interface ChecklistItem {
  key: ChecklistKey;
  title: string;
  hint: string;
  done: boolean;
}

const MANAGERS: Role[] = ["owner", "admin"];
const EDITORS: Role[] = ["owner", "admin", "builder"];

interface Def {
  key: ChecklistKey;
  title: string;
  hint: string;
  roles: Role[];
  isDone: (s: OnboardingStatus) => boolean;
}

const DEFS: Def[] = [
  {
    key: "ai",
    title: "AI 연결 등록하기",
    hint: "관리 > AI 모델에서 키를 넣고 '연결 테스트'를 눌러요.",
    roles: MANAGERS,
    isDone: (s) => s.ai_connected,
  },
  {
    key: "samples",
    title: "샘플 넣고 둘러보기",
    hint: "배우기에서 '샘플 넣기'를 누르면 따라 해 볼 앱 11개가 생겨요.",
    roles: EDITORS,
    isDone: (s) => s.samples_installed,
  },
  {
    key: "app",
    title: "첫 앱 만들기",
    hint: "위 '말로 앱 만들기' 칸에 만들고 싶은 것을 적어요.",
    roles: EDITORS,
    isDone: (s) => s.app_created,
  },
  {
    key: "test",
    title: "테스트 실행해 보기",
    hint: "만들기 화면의 '테스트 실행'으로 결과를 확인해요.",
    roles: EDITORS,
    isDone: (s) => s.test_run,
  },
  {
    key: "deploy",
    title: "버전 저장하고 배포하기",
    hint: "'버전 저장' 뒤 배포·설정에서 공유 링크를 만들어요.",
    roles: EDITORS,
    isDone: (s) => s.deployed,
  },
  {
    key: "team",
    title: "팀원 초대하기",
    hint: "워크스페이스 > 멤버에서 이메일로 초대 링크를 만들어요.",
    roles: MANAGERS,
    isDone: (s) => s.team_invited,
  },
];

export function checklistItems(
  role: Role | null,
  status: OnboardingStatus | undefined,
  stepsDone: string[] = [],
): ChecklistItem[] {
  if (!role) return [];
  return DEFS.filter((d) => d.roles.includes(role)).map((d) => ({
    key: d.key,
    title: d.title,
    hint: d.hint,
    // 한 번 끝낸 일은(앱을 지워도) 끝난 것으로 둔다
    done: stepsDone.includes(d.key) || Boolean(status && d.isDone(status)),
  }));
}

/** 이번에 새로 끝난 항목(내 기록에 더할 것) */
export function newlyDone(items: ChecklistItem[], stepsDone: string[] = []): string[] {
  return items.filter((i) => i.done && !stepsDone.includes(i.key)).map((i) => i.key);
}
