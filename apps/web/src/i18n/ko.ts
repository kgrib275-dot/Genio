// 한국어 문구. i18n 키만 먼저 준비해 둔다(설계서 §13).
export const ko = {
  appName: "제니오",
  tagline: "말로 만드는 나만의 앱",
  nav: {
    dashboard: "대시보드",
    knowledge: "지식베이스",
    connectors: "연결 정보",
    market: "마켓",
    workspace: "워크스페이스",
  },
  common: {
    save: "저장",
    cancel: "취소",
    delete: "삭제",
    create: "만들기",
    close: "닫기",
    loading: "불러오는 중…",
    logout: "로그아웃",
    retry: "다시 시도",
    copy: "복사",
    copied: "복사했어요",
    noPermission: "이 작업은 관리자만 할 수 있어요.",
  },
  roles: {
    owner: "소유자",
    admin: "관리자",
    builder: "제작자",
    operator: "운영자",
    member: "사용자",
  },
  appTypes: {
    chat: "챗봇",
    workflow: "흐름",
    form: "입력 양식",
  },
  marketTypes: {
    template: "템플릿",
    node: "노드",
    connector: "서비스 연결",
    prompt_pack: "프롬프트 모음",
  },
} as const;

export type RoleKey = keyof typeof ko.roles;
