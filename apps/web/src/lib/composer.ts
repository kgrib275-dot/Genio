// 채팅 입력창의 보내기 키 규칙. '내 설정 > Enter로 보내기'를 따른다.
// 켜짐: Enter 보내기, Shift+Enter 줄바꿈. 꺼짐: Enter 줄바꿈, Ctrl/⌘+Enter 보내기.
import { useQuery } from "@tanstack/react-query";
import type { KeyboardEvent } from "react";
import { api } from "@/lib/api/client";
import type { Me } from "@/lib/api/types";

const KEY = "genio.enterToSend";

export function storedEnterToSend(): boolean {
  try {
    return window.localStorage.getItem(KEY) !== "0";
  } catch {
    return true;
  }
}

/** 로그인하지 않은 공유 화면에서도 같은 규칙을 쓰도록 이 기기에 적어 둔다 */
export function rememberEnterToSend(value: boolean): void {
  try {
    window.localStorage.setItem(KEY, value ? "1" : "0");
  } catch {
    // 기억하지 못하면 기본값(Enter로 보내기)을 쓴다
  }
}

/** 이미 불러온 내 정보가 있으면 그 값을, 없으면 이 기기에 적어 둔 값을 쓴다(새로 요청하지 않음) */
export function useEnterToSend(): boolean {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/me"), enabled: false });
  const pref = me.data?.preferences?.enter_to_send;
  return typeof pref === "boolean" ? pref : storedEnterToSend();
}

export function isSendKey(e: KeyboardEvent<HTMLElement>, enterToSend: boolean): boolean {
  if (e.key !== "Enter" || e.nativeEvent.isComposing) return false;
  if (enterToSend) return !e.shiftKey;
  return e.ctrlKey || e.metaKey;
}

export function sendHint(enterToSend: boolean): string {
  return enterToSend ? "Enter 보내기 · Shift+Enter 줄바꿈" : "Ctrl+Enter 보내기 · Enter 줄바꿈";
}
