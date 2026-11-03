import { applyPatch, emptyGraph, touchedNodeIds } from "@/store/canvas";
import type { Graph } from "@/lib/api/types";

const base: Graph = {
  ...emptyGraph(),
  nodes: [
    { id: "n1", type: "input", position: { x: 0, y: 0 }, data: { label: "입력" } },
    {
      id: "n2",
      type: "output",
      position: { x: 300, y: 0 },
      data: { label: "결과", template: "a" },
    },
  ],
  edges: [{ id: "e1", source: "n1", target: "n2" }],
};

describe("applyPatch", () => {
  it("노드를 추가하고 같은 id면 바꿔 끼운다", () => {
    const g = applyPatch(base, [
      {
        op: "add_node",
        node: { id: "n3", type: "llm", position: { x: 1, y: 2 }, data: { label: "AI" } },
      },
      {
        op: "add_node",
        node: { id: "n3", type: "llm", position: { x: 1, y: 2 }, data: { label: "AI2" } },
      },
    ]);
    expect(g.nodes.map((n) => n.id)).toEqual(["n1", "n2", "n3"]);
    expect(g.nodes[2]?.data.label).toBe("AI2");
    expect(base.nodes).toHaveLength(2);
  });

  it("노드 data를 합쳐서 고친다", () => {
    const g = applyPatch(base, [{ op: "update_node", id: "n2", data: { template: "b" } }]);
    expect(g.nodes[1]?.data).toEqual({ label: "결과", template: "b" });
  });

  it("노드를 지우면 이어진 선도 지운다", () => {
    const g = applyPatch(base, [{ op: "remove_node", id: "n2" }]);
    expect(g.nodes.map((n) => n.id)).toEqual(["n1"]);
    expect(g.edges).toEqual([]);
  });

  it("선을 추가하고 지운다", () => {
    const added = applyPatch(base, [
      { op: "add_edge", edge: { id: "e2", source: "n2", target: "n1", sourceHandle: "c1" } },
    ]);
    expect(added.edges).toHaveLength(2);
    expect(added.edges[1]?.sourceHandle).toBe("c1");
    const removed = applyPatch(added, [{ op: "remove_edge", id: "e1" }]);
    expect(removed.edges.map((e) => e.id)).toEqual(["e2"]);
  });

  it("하이라이트할 노드 id를 모은다", () => {
    expect(
      touchedNodeIds([
        { op: "update_node", id: "n2", data: {} },
        { op: "add_edge", edge: { id: "e9", source: "n1", target: "n3" } },
        { op: "remove_node", id: "n4" },
      ]).sort(),
    ).toEqual(["n1", "n2", "n3"]);
  });
});
