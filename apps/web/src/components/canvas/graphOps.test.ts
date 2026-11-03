import {
  addNote,
  autoLayout,
  copySelection,
  emptyHistory,
  pasteClip,
  record,
  redo,
  remapRefs,
  removeNote,
  toggleDisabled,
  undo,
} from "@/components/canvas/graphOps";
import type { Graph } from "@/lib/api/types";

const g = (): Graph => ({
  version: 1,
  variables: {},
  nodes: [
    { id: "n1", type: "input", position: { x: 0, y: 0 }, data: {} },
    { id: "n2", type: "llm", position: { x: 300, y: 0 }, data: { prompt: "{{n1.message}}" } },
    { id: "n3", type: "output", position: { x: 600, y: 0 }, data: { template: "{{ n2.text }}" } },
  ],
  edges: [
    { id: "e1", source: "n1", target: "n2" },
    { id: "e2", source: "n2", target: "n3" },
  ],
});

describe("복사·붙여넣기", () => {
  it("고른 단계끼리의 연결만 복사한다", () => {
    const clip = copySelection(g(), ["n2", "n3"]);
    expect(clip?.nodes.map((n) => n.id)).toEqual(["n2", "n3"]);
    expect(clip?.edges.map((e) => e.id)).toEqual(["e2"]);
    expect(copySelection(g(), [])).toBeNull();
  });

  it("새 id로 붙이고 연결·참조를 새 id로 바꾼다(밖의 참조는 그대로)", () => {
    const base = g();
    const clip = copySelection(base, ["n2", "n3"]);
    if (!clip) throw new Error("clip");
    const r = pasteClip(base, clip);
    expect(r.newIds).toEqual(["n4", "n5"]);
    const n4 = r.graph.nodes.find((n) => n.id === "n4");
    const n5 = r.graph.nodes.find((n) => n.id === "n5");
    expect(n4?.data.prompt).toBe("{{n1.message}}");
    expect(n5?.data.template).toBe("{{ n4.text }}");
    expect(n4?.position).toEqual({ x: 340, y: 40 });
    expect(r.graph.edges.at(-1)).toEqual({ id: "e3", source: "n4", target: "n5" });
    for (const id of r.newIds) expect(id).toMatch(/^[A-Za-z_][A-Za-z0-9_]*$/);
  });

  it("시작 단계는 하나만 둘 수 있어 붙여넣기에서 뺀다", () => {
    const base = g();
    const clip = copySelection(base, ["n1", "n2"]);
    if (!clip) throw new Error("clip");
    const r = pasteClip(base, clip);
    expect(r.skipped).toBe(1);
    expect(r.newIds).toEqual(["n4"]);
    expect(r.graph.edges).toHaveLength(2);
  });

  it("참조 바꾸기는 문자열·배열·객체 안까지", () => {
    const m = new Map([["n2", "n9"]]);
    expect(remapRefs({ a: ["{{n2.x}} {{n22.x}}", "{{n2}}"] }, m)).toEqual({
      a: ["{{n9.x}} {{n22.x}}", "{{n9}}"],
    });
  });
});

describe("끄기·되돌리기·정렬·메모", () => {
  it("하나라도 켜져 있으면 모두 끄고, 모두 꺼져 있으면 켠다", () => {
    const off = toggleDisabled(g(), ["n2", "n3"]);
    expect(off.nodes.filter((n) => n.disabled).map((n) => n.id)).toEqual(["n2", "n3"]);
    const on = toggleDisabled(off, ["n2", "n3"]);
    expect(on.nodes.some((n) => "disabled" in n)).toBe(false);
  });

  it("기록은 최대 개수를 넘지 않고, 되돌리기·다시 하기가 짝을 이룬다", () => {
    let h = emptyHistory();
    for (let i = 0; i < 60; i++) h = record(h, { ...g(), version: i });
    expect(h.past).toHaveLength(50);
    expect(h.past[0]?.version).toBe(10);
    const cur = { ...g(), version: 99 };
    const u = undo(h, cur);
    expect(u?.graph.version).toBe(59);
    const r = u && redo(u.history, u.graph);
    expect(r?.graph.version).toBe(99);
    expect(undo(emptyHistory(), cur)).toBeNull();
    // 새 기록이 생기면 다시 하기는 비운다
    expect(record(u?.history ?? h, cur).future).toHaveLength(0);
  });

  it("자동 정렬은 왼쪽에서 오른쪽으로 놓는다", () => {
    const shuffled: Graph = {
      ...g(),
      nodes: g().nodes.map((n, i) => ({ ...n, position: { x: 900 - i * 300, y: i * 50 } })),
    };
    const out = autoLayout(shuffled);
    const x = (id: string) => out.nodes.find((n) => n.id === id)?.position.x ?? 0;
    expect(x("n1")).toBeLessThan(x("n2"));
    expect(x("n2")).toBeLessThan(x("n3"));
  });

  it("메모를 더하고 지우면 notes가 비어 저장 형식이 그대로다", () => {
    const [withNote, id] = addNote(g(), { x: 1, y: 2 });
    expect(id).toBe("m1");
    expect(withNote.notes?.[0]).toMatchObject({ id: "m1", color: "yellow", width: 220 });
    expect("notes" in removeNote(withNote, id)).toBe(false);
  });
});
