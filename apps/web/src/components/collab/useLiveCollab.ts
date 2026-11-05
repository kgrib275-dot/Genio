// 빌더를 열어 둔 동안: 같이 보는 사람 표시, 남이 저장한 흐름 반영, 댓글 갱신(v0.9).
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { toast } from "@/components/ui/toast-store";
import {
  CLIENT_ID,
  fetchDraft,
  postPresence,
  streamLive,
  type CommentChangedEvent,
  type DraftChangedEvent,
  type PresenceUser,
} from "@/lib/api/collab";
import { normalizeGraph } from "@/lib/api/types";
import { changedNodeIds, sameGraph } from "@/lib/mergeUi";
import { useCanvas } from "@/store/canvas";
import { useCollab } from "@/store/collab";

const HEARTBEAT_MS = 10_000;

/** 서버의 최신 작업본을 받아, 내가 고치는 중이 아니면 캔버스에 반영한다. 반영했으면 true. */
export async function pullRemoteDraft(appId: string, byName?: string): Promise<boolean> {
  const detail = await fetchDraft(appId);
  const rev = detail.draft_rev ?? 0;
  const collab = useCollab.getState();
  if (collab.rev !== null && rev <= collab.rev) return false;
  const canvas = useCanvas.getState();
  if (canvas.dirty) {
    // 내가 고치는 중이라 화면은 그대로 둔다. 저장할 때 서버가 겹치지 않는 변경을 합친다.
    collab.setRemoteRev(rev);
    return false;
  }
  const next = normalizeGraph(detail.draft_graph);
  collab.setRev(rev);
  if (sameGraph(canvas.graph, next)) return false;
  canvas.replaceFromServer(next, changedNodeIds(canvas.graph, next));
  if (byName) toast.info(`${byName}님이 흐름을 고쳐서 화면에 반영했어요.`);
  return true;
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(t);
      resolve();
    });
  });
}

/** appId 빌더에 붙어 있는 동안 알림 줄기(SSE)를 받고, 10초마다 내 위치를 알린다. */
export function useLiveCollab(appId: string, enabled: boolean): void {
  const qc = useQueryClient();
  const selectedId = useCanvas((s) => s.selectedId);
  const dirty = useCanvas((s) => s.dirty);
  const latest = useRef({ selectedId, dirty });
  latest.current = { selectedId, dirty };

  // 알림 줄기: 끊기면 잠시 뒤 다시 이어 받고, 이어질 때마다 놓친 변경이 없는지 확인한다
  useEffect(() => {
    if (!appId || !enabled) return;
    const ctrl = new AbortController();
    let busy = false;
    const names = (id: string | null): string | undefined =>
      useCollab.getState().users.find((u) => u.user_id === id)?.name;

    const onEvent = (ev: { event: string; data: unknown }) => {
      const collab = useCollab.getState();
      if (ev.event === "hello") {
        collab.setLive(true);
        void pullRemoteDraft(appId).catch(() => undefined); // 끊긴 사이 놓친 변경 확인
      } else if (ev.event === "presence") {
        collab.setUsers((ev.data as { users?: PresenceUser[] }).users ?? []);
      } else if (ev.event === "draft_changed") {
        const d = ev.data as DraftChangedEvent;
        if (d.client_id === CLIENT_ID) return; // 내가 저장한 것
        if (collab.rev !== null && d.rev <= collab.rev) return;
        if (busy) return;
        busy = true;
        void pullRemoteDraft(appId, names(d.user_id))
          .catch(() => undefined)
          .finally(() => {
            busy = false;
          });
      } else if (ev.event === "comment_changed") {
        const d = ev.data as CommentChangedEvent;
        void qc.invalidateQueries({ queryKey: ["comments", appId] });
        if (d.client_id !== CLIENT_ID && d.action === "create" && d.user_id !== collab.me) {
          toast.info(`${names(d.user_id) ?? "다른 사람"}님이 댓글을 남겼어요.`);
        }
      }
    };

    void (async () => {
      let delay = 1000;
      while (!ctrl.signal.aborted) {
        try {
          await streamLive(appId, onEvent, ctrl.signal);
          delay = 1000;
        } catch (err) {
          if (err instanceof DOMException && err.name === "AbortError") return;
        }
        useCollab.getState().setLive(false);
        await sleep(delay, ctrl.signal);
        delay = Math.min(delay * 2, 15_000);
      }
    })();
    return () => ctrl.abort();
  }, [appId, enabled, qc]);

  // 내 위치 알리기: 10초마다, 그리고 고른 단계·편집 상태가 바뀌면 곧바로
  useEffect(() => {
    if (!appId || !enabled) return;
    const beat = () => {
      const { selectedId: node, dirty: editing } = latest.current;
      void postPresence(appId, { node_id: node, editing }).catch(() => undefined);
    };
    beat();
    const t = setInterval(beat, HEARTBEAT_MS);
    // 탭을 닫거나 다른 주소로 가는 순간에도 '떠남'을 알린다(알리지 못해도 30초 뒤에는 목록에서 빠진다)
    const leave = () => void postPresence(appId, { leave: true }, true).catch(() => undefined);
    window.addEventListener("pagehide", leave);
    return () => {
      clearInterval(t);
      window.removeEventListener("pagehide", leave);
      leave();
    };
  }, [appId, enabled]);

  useEffect(() => {
    if (!appId || !enabled) return;
    const t = setTimeout(() => {
      void postPresence(appId, { node_id: selectedId, editing: dirty }).catch(() => undefined);
    }, 400);
    return () => clearTimeout(t);
  }, [appId, enabled, selectedId, dirty]);
}
