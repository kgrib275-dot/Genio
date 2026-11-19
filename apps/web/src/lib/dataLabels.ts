// 데이터 키를 쉬운 말로 바꾸는 이름표(DataView·활동 기록이 함께 씀)
/** 자주 나오는 키를 쉬운 말로 */
const KEY_LABELS: Record<string, string> = {
  input: "입력",
  output: "출력",
  inputs: "입력",
  outputs: "출력",
  text: "글",
  answer: "답변",
  question: "질문",
  query: "질문",
  message: "메시지",
  messages: "메시지",
  content: "내용",
  result: "결과",
  results: "결과",
  error: "오류",
  status: "상태",
  name: "이름",
  title: "제목",
  description: "설명",
  email: "이메일",
  role: "역할",
  from: "이전",
  to: "이후",
  user_id: "사용자",
  app_id: "앱",
  kb_id: "지식베이스",
  project_id: "프로젝트",
  version: "버전",
  model: "모델",
  provider: "AI 서비스",
  prompt: "지시문",
  system: "시스템 지시",
  temperature: "창의성",
  tokens: "토큰",
  input_tokens: "입력 토큰",
  output_tokens: "출력 토큰",
  cost: "비용",
  latency_ms: "걸린 시간(ms)",
  url: "주소",
  method: "방식",
  headers: "헤더",
  body: "본문",
  score: "점수",
  source: "출처",
  sources: "출처",
  citations: "출처",
  category: "분류",
  label: "이름표",
  value: "값",
  values: "값",
  items: "항목",
  count: "개수",
  created_at: "만든 때",
  updated_at: "바꾼 때",
  approved: "승인",
  dry_run: "시험 모드로 실행",
  sent: "실제로 보냄",
  preview: "보낼 내용(미리보기)",
  passed: "통과 여부(참이면 통과)",
  blocked: "걸림 여부",
  reasons: "걸린 이유",
  notes: "참고",
  tool_calls: "쓴 도구",
  reason: "이유",
  type: "종류",
  nodes: "단계",
  edges: "연결",
  key: "키",
  enabled: "켜짐",
  visibility: "공개 범위",
  allow_signup: "회원가입 허용",
  require_email_verification: "가입 시 이메일 확인 필수",
  prefix: "키 앞자리",
  template: "템플릿",
  template_key: "템플릿",
  price: "가격",
  channel: "배포 방식",
  version_id: "버전",
  filename: "파일 이름",
  size: "크기",
  chunks: "조각 수",
  user_ids: "구성원",
  color: "색",
  approve: "승인",
};

export function keyLabel(k: string): string {
  return KEY_LABELS[k] ?? k;
}

/** 자주 나오는 값을 쉬운 말로 */
const VALUE_LABELS: Record<string, string> = {
  private: "비공개",
  workspace: "워크스페이스 전체",
  public: "누구나",
  published: "배포됨",
  draft: "만드는 중",
  chat: "챗봇",
  workflow: "흐름",
  succeeded: "성공",
  failed: "실패",
  approved: "승인함",
  rejected: "거절함",
};

export function valueLabel(v: string): string {
  return VALUE_LABELS[v] ?? v;
}

/** 글 속의 {{n1.message}} 같은 값 끌어오기를 「질문」처럼 사람 말로 바꿔 보여 준다(보기용, 저장값은 그대로). */
export function humanizeRefs(text: string): string {
  return text.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (_m, ref: string) => {
    const last =
      ref
        .split(/[.[\]]/)
        .filter(Boolean)
        .pop() ?? ref;
    return `「${keyLabel(last)}」`;
  });
}
