// 작업본 저장(v0.9): 내가 불러온 번호와 함께 보내서, 남이 먼저 저장했어도 겹치지 않는 변경은 서버가 합친다.
import { saveDraftRev } from "@/lib/api/collab";
import { normalizeGraph } from "@/lib/api/types";
import { changedNodeIds } from "@/lib/mergeUi";
import { useCanvas } from "@/store/canvas";
import { useCollab } from "@/store/collab";

/** 지금 캔버스를 저장한다. 같은 곳을 서로 고쳐 합칠 수 없으면 'conflict'(충돌 창이 열린다). */
export async function saveDraftNow(appId: string): Promise<"saved" | "conflict"> {
  const before = useCanvas.getState();
  const seq = before.editSeq;
  const sent = before.graph;
  const collab = useCollab.getState();
  const result = await saveDraftRev(appId, sent, collab.rev);
  if (!result.ok) {
    collab.setConflict(result.conflict);
    return "conflict";
  }
  const { draft_rev: rev, merged, draft_graph: draftGraph } = result.detail;
  if (typeof rev === "number") collab.setRev(rev);
  collab.setRemoteRev(null);
  const canvas = useCanvas.getState();
  if (canvas.editSeq !== seq) return "saved"; // 저장하는 사이 또 고쳤다: 다음 저장이 이어서 한다
  if (merged) {
    // 서버가 남의 변경을 합쳐 줬다: 합친 흐름을 화면에 반영하고 바뀐 단계를 반짝인다
    const next = normalizeGraph(draftGraph);
    canvas.replaceFromServer(next, changedNodeIds(sent, next));
  } else {
    canvas.markSaved();
  }
  return "saved";
}

/** 충돌 창에서 고른 결과(흐름)를 상대 번호 기준으로 저장한다. */
export async function saveResolved(appId: string, graph: unknown, baseRev: number): Promise<void> {
  const canvas = useCanvas.getState();
  const next = normalizeGraph(graph as Parameters<typeof normalizeGraph>[0]);
  // 화면 흐름을 먼저 바꿔 두고(편집으로 기록되지 않게 서버 반영 방식으로), 저장한다
  canvas.replaceFromServer(next, []);
  let result;
  try {
    result = await saveDraftRev(appId, next, baseRev);
  } catch (err) {
    // 저장하지 못했다(네트워크 등): 바뀐 내용이 있다고 표시해 자동 저장이 다시 시도하게 한다
    useCanvas.setState((s) => ({ dirty: true, editSeq: s.editSeq + 1 }));
    throw err;
  }
  const collab = useCollab.getState();
  if (!result.ok) {
    // 그 사이 또 바뀌었다: 새 충돌로 다시 고르게 한다
    collab.setConflict(result.conflict);
    return;
  }
  if (typeof result.detail.draft_rev === "number") collab.setRev(result.detail.draft_rev);
  collab.setConflict(null);
  collab.setRemoteRev(null);
  useCanvas.getState().markSaved();
}

/** '상대가 저장한 흐름으로 새로 불러오기'. 내 변경은 버린다. */
export function adoptTheirs(theirs: unknown, rev: number): void {
  const next = normalizeGraph(theirs as Parameters<typeof normalizeGraph>[0]);
  const canvas = useCanvas.getState();
  canvas.replaceFromServer(next, changedNodeIds(canvas.graph, next));
  const collab = useCollab.getState();
  collab.setRev(rev);
  collab.setConflict(null);
  collab.setRemoteRev(null);
}
