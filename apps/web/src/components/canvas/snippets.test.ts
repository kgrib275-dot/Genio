// 스니펫 끼워 넣기: 한가운데에 놓기, 새 id로 바꾸고 안쪽 참조 이어 주기, 바깥 참조 표시 유지.
import { centerOffset, pasteClip, type Clip } from "@/components/canvas/graphOps";
import type { Graph } from "@/lib/api/types";
import { useCanvas } from "@/store/canvas";

const clip = (): Clip => ({
  nodes: [
    {
      id: "n3",
      type: "http",
      position: { x: 0, y: 0 },
      data: { label: "가져오기", url: "https://x/{{__outer.n1.q}}" },
    },
    {
      id: "n4",
      type: "template",
      position: { x: 300, y: 100 },
      data: { template: "{{n3.body}} {{ n3.status }}" },
    },
  ],
  edges: [{ id: "e5", source: "n3", target: "n4" }],
});

const host = (): Graph => ({
  version: 1,
  variables: {},
  nodes: [
    { id: "n1", type: "input", position: { x: 0, y: 0 }, data: { fields: [{ key: "q" }] } },
    { id: "n2", type: "output", position: { x: 600, y: 0 }, data: { template: "{{n1.q}}" } },
    { id: "n3", type: "template", position: { x: 300, y: 0 }, data: { template: "겹치는 id" } },
  ],
  edges: [{ id: "e1", source: "n1", target: "n2" }],
});

describe("스니펫 끼워 넣기", () => {
  test("묶음의 한가운데가 원하는 좌표에 온다", () => {
    const off = centerOffset(clip(), { x: 500, y: 300 });
    // 가로: (0 + 300 + 240) / 2 = 270, 세로: (0 + 100 + 110) / 2 = 105
    expect(off).toEqual({ x: 230, y: 195 });
    expect(centerOffset({ nodes: [], edges: [] }, { x: 5, y: 5 })).toEqual({ x: 0, y: 0 });
  });

  test("새 id를 받고 안쪽 참조·연결은 따라가며 바깥 참조 표시는 그대로", () => {
    const r = pasteClip(host(), clip(), centerOffset(clip(), { x: 500, y: 300 }));
    expect(r.newIds).toEqual(["n4", "n5"]); // 겹치던 n3·n4 대신 이어지는 번호
    const nodes = r.graph.nodes;
    const http = nodes.find((n) => n.id === "n4");
    const tmpl = nodes.find((n) => n.id === "n5");
    expect(http?.position).toEqual({ x: 230, y: 195 });
    expect(tmpl?.data.template).toBe("{{n4.body}} {{ n4.status }}");
    expect(String(http?.data.url)).toContain("{{__outer.n1.q}}"); // 바깥 값은 조용히 이어지지 않는다
    const added = r.graph.edges.filter((e) => e.id !== "e1");
    expect(added.map((e) => [e.source, e.target])).toEqual([["n4", "n5"]]);
    expect(host().nodes.find((n) => n.id === "n3")?.data.template).toBe("겹치는 id"); // 원래 단계는 그대로
  });

  test("저장소의 insertSnippet은 끼워 넣은 단계를 고른 상태로 둔다", () => {
    useCanvas.getState().load("app-1", host());
    const res = useCanvas.getState().insertSnippet(clip(), { x: 400, y: 200 });
    expect(res).toEqual({ pasted: 2, skipped: 0 });
    const s = useCanvas.getState();
    expect(s.graph.nodes).toHaveLength(5);
    expect(s.selectedIds).toEqual(["n4", "n5"]);
    s.undo();
    expect(useCanvas.getState().graph.nodes).toHaveLength(3);
  });

  test("시작(입력) 단계가 있고 흐름에 이미 시작이 있으면 건너뛴다", () => {
    const c: Clip = {
      nodes: [{ id: "n9", type: "input", position: { x: 0, y: 0 }, data: {} }],
      edges: [],
    };
    const r = pasteClip(host(), c);
    expect(r.skipped).toBe(1);
    expect(r.newIds).toEqual([]);
  });
});
