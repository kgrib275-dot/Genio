// v0.6: 목록 설정(한 번에 보기 개수·필터)을 계정별로 서버(개인 설정 lists)에 저장한다.
// 여러 목록을 빠르게 바꿔도 0.6초 모아서 한 번에 보낸다. 실패해도 화면 동작에는 문제없다.
import type { QueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { ListPref, Me } from "@/lib/api/types";

const pending = new Map<string, ListPref>();
let timer: ReturnType<typeof setTimeout> | null = null;

export function readListPref(qc: QueryClient | undefined, key: string): ListPref | undefined {
  return qc?.getQueryData<Me>(["me"])?.preferences?.lists?.[key];
}

export function saveListPref(qc: QueryClient | undefined, key: string, pref: ListPref): void {
  if (!qc) return;
  const me = qc.getQueryData<Me>(["me"]);
  if (!me) return; // 로그인하지 않은 화면(공유 링크 등)은 저장하지 않는다
  const lists = me.preferences?.lists ?? {};
  const next: ListPref = { ...(lists[key] ?? {}), ...pref };
  qc.setQueryData<Me>(["me"], {
    ...me,
    preferences: { ...me.preferences, lists: { ...lists, [key]: next } },
  });
  pending.set(key, { ...(pending.get(key) ?? {}), ...pref });
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => {
    const body = Object.fromEntries(pending);
    pending.clear();
    timer = null;
    api.patch<Me>("/me", { preferences: { lists: body } }).catch(() => {
      // 저장하지 못해도 이 화면에서는 고른 대로 보인다
    });
  }, 600);
}
