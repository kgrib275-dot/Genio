// v0.4 챗 경험: 공개 챗·대화로 시험하기가 함께 쓰는 타입, 전송(transport), 지난 대화 저장, 내보내기, 위젯 모양.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, apiFetch } from "@/lib/api/client";
import { sendPublicChat } from "@/lib/api/resources";
import { streamSSE, type SSEEvent } from "@/lib/api/sse";
import type {
  Citation,
  Deployment,
  PublicAppV2,
  PublicFeatures,
  Rating,
  StoredFile,
} from "@/lib/api/types";
import { sendPublicFeedback, uploadPublicFile } from "@/lib/api/v2";
import { fetchSessionState, requestHandoff, type SessionState } from "@/lib/api/v5a";

// ---------------- 위젯·공유 챗 모양 ----------------
export interface Appearance {
  primary_color: string;
  position: "right" | "left";
  launcher_text: string;
  greeting: string;
  open_on_load: boolean;
  width: number;
  height: number;
  title: string;
  /** v0.8: 링크를 공유할 때 메신저에 뜨는 미리보기 */
  share_title: string;
  share_description: string;
  /** 썸네일로 올린 파일 id(없으면 기본 그림) */
  share_image: string;
  /** v0.8 웹앱 로고로 올린 파일 id(없으면 기본 아이콘) */
  share_logo: string;
}

export const DEFAULT_APPEARANCE: Appearance = {
  primary_color: "#4f46e5",
  position: "right",
  launcher_text: "",
  greeting: "",
  open_on_load: false,
  width: 380,
  height: 600,
  title: "",
  share_title: "",
  share_description: "",
  share_image: "",
  share_logo: "",
};

export const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

export function appearanceOf(v: Partial<Appearance> | null | undefined): Appearance {
  const a = { ...DEFAULT_APPEARANCE, ...(v ?? {}) };
  if (!HEX_COLOR.test(a.primary_color)) a.primary_color = DEFAULT_APPEARANCE.primary_color;
  return a;
}

export type DeploymentV4 = Deployment & { appearance?: Partial<Appearance> };
export type PublicAppV4 = PublicAppV2 & { appearance?: Partial<Appearance> };

export function useUpdateAppearance(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { deploymentId: string; appearance: Appearance }) =>
      api.patch<DeploymentV4>(`/deployments/${v.deploymentId}`, { appearance: v.appearance }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["deployments", appId] }),
  });
}

// ---------------- 대화 한 줄 ----------------
export interface ChatLine {
  id: number;
  role: "user" | "assistant" | "error";
  text: string;
  hint?: string;
  messageId?: string;
  citations?: Citation[];
  suggestions?: string[];
  moderated?: boolean;
  annotated?: boolean;
  rating?: Rating | null;
  files?: StoredFile[];
  /** 답 조각이 오는 중 */
  streaming?: boolean;
  /** 사용자가 멈춤 */
  stopped?: boolean;
  createdAt?: string;
  /** 사람(상담원)이 쓴 답 */
  agent?: boolean;
  /** 서버 메시지 id(늦게 온 답·상담원 답을 다시 읽을 때 겹치지 않게) */
  serverId?: string;
}

export interface SessionMessage {
  id: string;
  role: "user" | "assistant" | "system" | "agent";
  content: string;
  created_at: string;
  feedback: Rating | null;
  citations?: Citation[];
  moderated?: boolean;
  annotated?: boolean;
}

export interface ChatSendBody {
  message: string;
  session_id?: string;
  input?: Record<string, unknown>;
  files?: string[];
}

/** 챗 화면이 서버와 이야기하는 방법. 공개 챗·대화로 시험하기가 다르게 채운다. */
export interface ChatTransport {
  send: (body: ChatSendBody, onEvent: (ev: SSEEvent) => void, signal: AbortSignal) => Promise<void>;
  feedback?: (messageId: string, rating: Rating | null) => Promise<unknown>;
  upload?: (file: File) => Promise<StoredFile>;
  loadSession?: (sessionId: string) => Promise<SessionMessage[]>;
  /** 대화 상태(상담원 연결 중인지, 사람을 기다리는 실행이 있는지) */
  sessionState?: (sessionId: string) => Promise<SessionState>;
  /** '상담원 연결' 버튼 */
  requestHandoff?: (sessionId: string) => Promise<unknown>;
}

export function publicTransport(token: string): ChatTransport {
  return {
    send: (body, onEvent, signal) => sendPublicChat(token, body, onEvent, signal),
    feedback: (messageId, rating) => sendPublicFeedback(token, messageId, rating),
    upload: (file) => uploadPublicFile(token, file),
    loadSession: (sid) =>
      apiFetch<SessionMessage[]>(
        `/public/apps/${token}/sessions/${encodeURIComponent(sid)}/messages`,
      ),
    sessionState: (sid) => fetchSessionState(token, sid),
    requestHandoff: (sid) => requestHandoff(token, sid),
  };
}

export function sendPreviewChat(
  appId: string,
  body: ChatSendBody,
  onEvent: (ev: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamSSE(`/apps/${appId}/preview/chat`, {
    method: "POST",
    body: { message: body.message, session_id: body.session_id, input: body.input },
    onEvent,
    signal,
  });
}

export function previewTransport(appId: string): ChatTransport {
  return { send: (body, onEvent, signal) => sendPreviewChat(appId, body, onEvent, signal) };
}

export function linesFromSession(msgs: SessionMessage[], nextId: () => number): ChatLine[] {
  return msgs
    .filter((m) => m.role === "user" || m.role === "assistant" || m.role === "agent")
    .map((m) => ({
      id: nextId(),
      role: (m.role === "user" ? "user" : "assistant") as "user" | "assistant",
      agent: m.role === "agent" || undefined,
      serverId: m.id,
      text: m.content,
      messageId: m.role === "assistant" ? m.id : undefined,
      rating: m.feedback ?? null,
      citations: m.citations && m.citations.length ? m.citations : undefined,
      moderated: m.moderated,
      annotated: m.annotated,
      createdAt: m.created_at,
    }));
}

// ---------------- 지난 대화 목록(이 브라우저에만) ----------------
export interface SessionEntry {
  session_id: string;
  title: string;
  updated_at: string;
}

const MAX_SESSIONS = 30;
const sessionsKey = (key: string) => `genio.chat.sessions.${key}`;

export function loadSessions(key: string): SessionEntry[] {
  try {
    const raw = window.localStorage.getItem(sessionsKey(key));
    const list = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(list)
      ? (list as SessionEntry[]).filter((s) => s && typeof s.session_id === "string")
      : [];
  } catch {
    return [];
  }
}

function saveSessions(key: string, list: SessionEntry[]) {
  try {
    window.localStorage.setItem(sessionsKey(key), JSON.stringify(list.slice(0, MAX_SESSIONS)));
  } catch {
    // 기억하지 못해도 대화는 계속된다
  }
}

/** 새 대화면 맨 앞에 넣고, 있던 대화면 시간을 바꿔 맨 앞으로 */
export function upsertSession(key: string, sessionId: string, title: string): SessionEntry[] {
  const list = loadSessions(key);
  const old = list.find((s) => s.session_id === sessionId);
  const entry: SessionEntry = {
    session_id: sessionId,
    title: old?.title || title.slice(0, 40) || "새 대화",
    updated_at: new Date().toISOString(),
  };
  const next = [entry, ...list.filter((s) => s.session_id !== sessionId)];
  saveSessions(key, next);
  return next;
}

export function removeSession(key: string, sessionId: string): SessionEntry[] {
  const next = loadSessions(key).filter((s) => s.session_id !== sessionId);
  saveSessions(key, next);
  return next;
}

// ---------------- 내보내기 ----------------
export function transcriptMarkdown(title: string, lines: ChatLine[]): string {
  const out = [`# ${title}`, "", `내보낸 때: ${new Date().toLocaleString("ko-KR")}`, ""];
  for (const l of lines) {
    if (l.role === "error") continue;
    out.push(`**${l.role === "user" ? "나" : title}**`, "", l.text, "");
  }
  return out.join("\n");
}

export function downloadText(filename: string, text: string, type = "text/markdown"): void {
  const blob = new Blob([text], { type: `${type};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ---------------- 위젯 안에서 닫기 ----------------
/** 위젯(iframe) 안에서 바깥 페이지에 '닫아 달라'고 알린다 */
export function askParentToClose(): void {
  try {
    window.parent?.postMessage({ type: "genio:close" }, "*");
  } catch {
    // 바깥 페이지가 없으면 무시
  }
}

export type { PublicFeatures };

// ---------------- 대화로 시험하기 ----------------
type GraphLike = { nodes?: { type: string; data?: Record<string, unknown> }[] } | null | undefined;

/** 작업본 그래프의 입력 단계에서 입력 항목을 꺼낸다(서버 input_fields와 같은 규칙) */
export function inputFieldsOfGraph(graph: GraphLike): PublicAppV2["input_fields"] {
  const node = graph?.nodes?.find((n) => n.type === "input");
  const fields = (node?.data?.fields ?? []) as {
    key?: string;
    label?: string;
    type?: string;
    required?: boolean;
  }[];
  return fields
    .filter((f) => f.key)
    .map((f) => ({
      key: String(f.key),
      label: f.label || String(f.key),
      type: f.type ?? "text",
      required: Boolean(f.required),
    }));
}
