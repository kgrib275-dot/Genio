// AI 자동 전환 순서·키 돌려쓰기 화면 도우미(v0.9). 순서 바꾸기·검사·글 만들기 같은 순수 함수.

export const MAX_LINKS = 5;

export type TriggerKey = "outage" | "rate_limit" | "content_filter" | "context_length" | "auth";

export interface ChainLink {
  provider_id: string;
  /** 비우면 그 연결의 기본 모델 */
  model: string;
}

export const DEFAULT_TRIGGERS: Record<TriggerKey, boolean> = {
  outage: true,
  rate_limit: true,
  content_filter: false,
  context_length: false,
  auth: false,
};

export const TRIGGERS: { key: TriggerKey; label: string; hint: string }[] = [
  {
    key: "outage",
    label: "서버 오류·연결 안 됨·시간 초과",
    hint: "AI 서비스가 잠깐 멈췄을 때",
  },
  {
    key: "rate_limit",
    label: "한도 초과",
    hint: "그 연결의 키를 모두 써 보고도 한도에 걸릴 때",
  },
  {
    key: "content_filter",
    label: "안전 정책으로 답하지 않음",
    hint: "다른 회사 모델이 답할 수도 있어서 선택 사항이에요",
  },
  {
    key: "context_length",
    label: "입력이 너무 김",
    hint: "더 긴 글을 받는 모델로 넘기고 싶을 때",
  },
  {
    key: "auth",
    label: "키 오류",
    hint: "키가 틀리거나 만료됐을 때(보통은 키부터 고쳐야 해요)",
  },
];

export const STRATEGIES: { value: string; label: string; hint: string }[] = [
  {
    value: "failover",
    label: "앞의 키부터",
    hint: "첫 키를 쓰다가 한도에 걸리면 다음 키로 넘어가요.",
  },
  {
    value: "round_robin",
    label: "돌아가며",
    hint: "호출할 때마다 키를 번갈아 써서 한도를 나눠 써요.",
  },
  { value: "weighted", label: "비중대로", hint: "비중이 큰 키를 더 자주 써요(1~10)." },
];

export function strategyLabel(value: string | undefined): string {
  return STRATEGIES.find((s) => s.value === value)?.label ?? "앞의 키부터";
}

/** index 줄을 dir(-1 위, +1 아래)로 한 칸 옮긴다. 끝이면 그대로. */
export function moveLink<T>(list: T[], index: number, dir: -1 | 1): T[] {
  const to = index + dir;
  if (index < 0 || index >= list.length || to < 0 || to >= list.length) return list;
  const next = [...list];
  const [item] = next.splice(index, 1);
  next.splice(to, 0, item as T);
  return next;
}

/** 같은 연결은 한 번만, 최대 MAX_LINKS개. */
export function addLink(list: ChainLink[], providerId: string, model = ""): ChainLink[] {
  if (!providerId || list.length >= MAX_LINKS || list.some((l) => l.provider_id === providerId))
    return list;
  return [...list, { provider_id: providerId, model }];
}

export function removeLink<T>(list: T[], index: number): T[] {
  return list.filter((_, i) => i !== index);
}

export function setLinkModel(list: ChainLink[], index: number, model: string): ChainLink[] {
  return list.map((l, i) => (i === index ? { ...l, model } : l));
}

/** 저장 전 한 줄 안내(문제가 없으면 null). 서버 검사와 같은 규칙. */
export function chainProblem(
  enabled: boolean,
  links: ChainLink[],
  triggers: Record<TriggerKey, boolean>,
): string | null {
  if (!enabled) return null;
  if (links.length === 0) return "대체할 AI 연결을 하나 이상 추가해 주세요.";
  if (!Object.values(triggers).some(Boolean)) return "넘어갈 조건을 하나 이상 켜 주세요.";
  return null;
}

/** 쉬는 시간 글: 75 → "1분 15초", 20 → "20초" */
export function cooldownText(seconds: number): string {
  if (seconds <= 0) return "";
  if (seconds < 60) return `${seconds}초`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m >= 60) return `${Math.floor(m / 60)}시간 ${m % 60}분`;
  return s ? `${m}분 ${s}초` : `${m}분`;
}
