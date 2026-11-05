// 동시 편집·댓글 화면 상태(v0.9): 서버 작업본 번호, 같이 보는 사람들, 충돌 창, 댓글 패널.
import { create } from "zustand";
import type { DraftConflict, PresenceUser } from "@/lib/api/collab";

export interface ComposeTarget {
  nodeId: string | null;
  x: number | null;
  y: number | null;
}

interface CollabState {
  appId: string;
  /** 내가 알고 있는 서버 작업본 번호. null이면 모르는 상태라 번호를 보내지 않는다(덮어쓰기). */
  rev: number | null;
  me: string;
  users: PresenceUser[];
  conflict: DraftConflict | null;
  /** 내가 고치는 동안 들어온 더 높은 서버 번호(저장할 때 서버가 합친다) */
  remoteRev: number | null;
  live: boolean;
  panelOpen: boolean;
  commentMode: boolean;
  compose: ComposeTarget | null;
  focusThreadId: string | null;

  start: (appId: string, rev: number | null, me: string) => void;
  setRev: (rev: number) => void;
  setUsers: (users: PresenceUser[]) => void;
  setConflict: (c: DraftConflict | null) => void;
  setRemoteRev: (rev: number | null) => void;
  setLive: (live: boolean) => void;
  openPanel: (open?: boolean) => void;
  setCommentMode: (on: boolean) => void;
  openCompose: (target: ComposeTarget | null) => void;
  focusThread: (id: string | null) => void;
}

export const useCollab = create<CollabState>((set) => ({
  appId: "",
  rev: null,
  me: "",
  users: [],
  conflict: null,
  remoteRev: null,
  live: false,
  panelOpen: false,
  commentMode: false,
  compose: null,
  focusThreadId: null,

  start: (appId, rev, me) =>
    set({
      appId,
      rev,
      me,
      users: [],
      conflict: null,
      remoteRev: null,
      live: false,
      commentMode: false,
      compose: null,
      focusThreadId: null,
    }),
  setRev: (rev) => set((s) => (s.rev === null || rev > s.rev ? { rev } : {})),
  setUsers: (users) => set({ users }),
  setConflict: (conflict) => set({ conflict }),
  setRemoteRev: (remoteRev) => set({ remoteRev }),
  setLive: (live) => set({ live }),
  openPanel: (open = true) => set({ panelOpen: open }),
  setCommentMode: (commentMode) => set({ commentMode }),
  openCompose: (compose) => set(compose ? { compose, panelOpen: true } : { compose: null }),
  focusThread: (focusThreadId) =>
    set(focusThreadId ? { focusThreadId, panelOpen: true } : { focusThreadId: null }),
}));
