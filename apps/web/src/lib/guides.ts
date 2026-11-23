// 목표별 단계 안내(가이드). 처음 쓰는 사람이 "무엇을 어디서 누르면 되는지"를 한 단계씩 따라가게 한다.
import type { Role } from "@/lib/api/types";

export interface GuideStep {
  title: string;
  body: string;
  /** 이 단계에서 눌러 이동하는 화면 */
  action?: { label: string; to: string };
}

export interface Guide {
  id: string;
  emoji: string;
  title: string;
  summary: string;
  /** make: 앱을 만드는 사람(제작자 이상) · use: 쓰는 사람 */
  audience: "make" | "use";
  steps: GuideStep[];
}

export const GUIDES: Guide[] = [
  {
    id: "docs",
    emoji: "📚",
    title: "내 문서로 답하는 챗봇",
    summary: "규정·매뉴얼을 올려 두면 챗봇이 그 내용으로 답해요.",
    audience: "make",
    steps: [
      {
        title: "문서 올리기",
        body: "규정이나 매뉴얼 파일(PDF·워드·텍스트)을 올려요. 파일 하나만 올려도 돼요.",
        action: { label: "문서 올리러 가기", to: "/knowledge" },
      },
      {
        title: "챗봇 만들기",
        body: "'내 문서로 챗봇 만들기'에서 올린 문서를 고르면 빌더가 챗봇을 만들어 줘요.",
        action: { label: "챗봇 만들러 가기", to: "/?guide=docbot" },
      },
      {
        title: "질문해 보기",
        body: "만들어지면 위쪽 '대화로 시험'을 눌러 문서에 있는 질문과 없는 질문을 하나씩 해 보세요. 없는 건 모른다고 답하면 잘 된 거예요.",
      },
      {
        title: "팀에 공유하기",
        body: "'공유·설정' 탭에서 공유 링크를 만들면 팀원이 바로 쓸 수 있어요.",
      },
    ],
  },
  {
    id: "auto",
    emoji: "⚙️",
    title: "반복 업무 자동화",
    summary: "매번 하던 일을 말로 적으면 자동으로 처리하는 흐름이 만들어져요.",
    audience: "make",
    steps: [
      {
        title: "하고 싶은 일을 말로 적기",
        body: "평소 말하듯 적어 보세요. 예: '고객 문의 메일을 분류해서 담당자 슬랙으로 보내 줘'",
        action: {
          label: "말로 적으러 가기",
          to: "/?guide=prompt&example=고객 문의 메일을 분류해서 담당자 슬랙으로 보내 줘",
        },
      },
      {
        title: "만들어진 흐름 확인하기",
        body: "빌더가 만든 단계가 오른쪽 그림으로 나와요. 이상한 곳은 왼쪽 대화창에 '이건 이렇게 바꿔 줘'라고 말하면 고쳐 줘요.",
      },
      {
        title: "테스트 실행하기",
        body: "위쪽 '테스트 실행'을 눌러 예시 입력으로 결과를 확인해요. 실제로 메일이나 슬랙을 보내지 않는 시험 모드도 있어요.",
      },
      {
        title: "저절로 돌게 하기",
        body: "'자동 실행' 탭에서 시간을 정하거나 '외부에서 받기'를 켜면 사람이 누르지 않아도 돌아요.",
      },
    ],
  },
  {
    id: "approval",
    emoji: "✅",
    title: "승인 받는 흐름",
    summary: "중요한 일은 담당자가 확인·승인한 뒤에만 진행되게 해요.",
    audience: "make",
    steps: [
      {
        title: "승인이 필요한 일을 말로 적기",
        body: "예: '휴가 신청을 받아서 팀장 승인을 받은 뒤 결과를 알려 줘'",
        action: {
          label: "말로 적으러 가기",
          to: "/?guide=prompt&example=휴가 신청을 받아서 팀장 승인을 받은 뒤 결과를 알려 줘",
        },
      },
      {
        title: "누가 승인하는지 확인하기",
        body: "만들어진 흐름의 '승인' 단계를 눌러 승인할 사람(역할)과 알림 방법을 확인해요.",
      },
      {
        title: "테스트로 한 번 돌려 보기",
        body: "'테스트 실행'을 눌러 보세요. 승인 단계에서 멈추고 '작업함'에 승인 요청이 생겨요.",
      },
      {
        title: "작업함에서 승인해 보기",
        body: "작업함에서 승인하면 흐름이 이어져 끝까지 돌아가요.",
        action: { label: "작업함 열기", to: "/tasks" },
      },
    ],
  },
  {
    id: "connect",
    emoji: "🔌",
    title: "외부 서비스 연결",
    summary: "슬랙·메일·노션 같은 서비스를 흐름에서 쓸 수 있게 연결해요.",
    audience: "make",
    steps: [
      {
        title: "새 서비스 둘러보기",
        body: "'이번 주 새 소식'에서 새로 나온 서비스를 보거나, '서비스 연결'에서 이름으로 찾아요.",
        action: { label: "연결 화면 열기", to: "/connectors" },
      },
      {
        title: "연결하기",
        body: "마음에 드는 서비스의 '연결하기'를 눌러요. 연결은 소유자·관리자만 할 수 있어요. 권한이 없으면 관리자에게 요청하세요.",
      },
      {
        title: "할 수 있는 일 확인하기",
        body: "연결한 뒤 '도구 보기'를 눌러 그 서비스가 해 줄 수 있는 일을 확인해요.",
      },
      {
        title: "흐름에서 쓰기",
        body: "빌더에게 'OO 서비스로 ~해 줘'라고 말하면 알아서 단계를 넣어 줘요.",
      },
    ],
  },
  {
    id: "chat",
    emoji: "💬",
    title: "챗봇에게 물어보기",
    summary: "팀이 만든 챗봇에게 궁금한 걸 물어봐요.",
    audience: "use",
    steps: [
      {
        title: "챗봇 고르기",
        body: "챗봇 모음에서 쓰고 싶은 챗봇을 골라요.",
        action: { label: "챗봇 모음 열기", to: "/hub" },
      },
      {
        title: "질문하기",
        body: "궁금한 걸 평소 말하듯 적어요. 챗봇이 모르는 건 모른다고 알려 줘요.",
      },
      {
        title: "답이 이상하면 알리기",
        body: "답 옆의 👎를 누르면 만든 사람에게 전달돼서 챗봇이 더 좋아져요.",
      },
    ],
  },
  {
    id: "tasks",
    emoji: "📋",
    title: "내가 할 일 처리하기",
    summary: "승인하거나 확인해 달라고 온 일을 처리해요.",
    audience: "use",
    steps: [
      {
        title: "작업함 열기",
        body: "빨간 숫자가 붙어 있으면 처리할 일이 있다는 뜻이에요.",
        action: { label: "작업함 열기", to: "/tasks" },
      },
      {
        title: "내용 보고 처리하기",
        body: "내용을 읽고 '승인' 또는 '반려'를 눌러요. 필요하면 이유를 한 줄 남겨요.",
      },
      {
        title: "처리한 일 확인하기",
        body: "처리하면 목록에서 사라지고, 흐름은 바로 이어서 진행돼요.",
      },
    ],
  },
];

const MAKERS: Role[] = ["owner", "admin", "builder"];

/** 이 역할에게 보여 줄 가이드(만드는 사람은 만들기 안내, 그 밖에는 쓰기 안내) */
export function guidesFor(role: Role | null): Guide[] {
  if (!role) return [];
  const audience = MAKERS.includes(role) ? "make" : "use";
  return GUIDES.filter((g) => g.audience === audience);
}

export function guideById(id: string): Guide | undefined {
  return GUIDES.find((g) => g.id === id);
}
