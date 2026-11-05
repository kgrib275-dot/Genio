import type { ConflictItem } from "@/lib/api/collab";
import {
  allChosen,
  applyChoices,
  changedNodeIds,
  conflictKey,
  defaultChoices,
  fieldLabel,
  groupConflicts,
  sameGraph,
  valueText,
  type Choices,
} from "@/lib/mergeUi";

const merged = {
  version: 1,
  nodes: [
    { id: "n1", type: "input", position: { x: 0, y: 0 }, data: { fields: [] } },
    {
      id: "n2",
      type: "template",
      position: { x: 300, y: 0 },
      data: { label: "다듬기", template: "상대 글" },
    },
    { id: "n3", type: "output", position: { x: 600, y: 0 }, data: { template: "끝" } },
  ],
  edges: [
    { id: "e1", source: "n1", target: "n2" },
    { id: "e2", source: "n2", target: "n3" },
  ],
  variables: { a: 5 },
};

const fieldConflict: ConflictItem = {
  kind: "node",
  node_id: "n2",
  field: "data.template",
  label: "다듬기",
  base: "원래",
  mine: "내 글",
  theirs: "상대 글",
};

test("칸 충돌: 내 것을 고르면 그 칸만 내 값이 되고 나머지는 합친 그대로", () => {
  const out = applyChoices(merged, [fieldConflict], { [conflictKey(fieldConflict)]: "mine" });
  const n2 = out.nodes?.find((n) => n.id === "n2");
  expect(n2?.data?.template).toBe("내 글");
  expect(n2?.data?.label).toBe("다듬기");
  // 원본은 바뀌지 않는다
  expect(merged.nodes[1]?.data.template).toBe("상대 글");
});

test("상대 것을 고르면(기본) 합친 결과 그대로", () => {
  const out = applyChoices(merged, [fieldConflict], defaultChoices([fieldConflict]));
  expect(out).toEqual(merged);
});

test("지움 vs 수정: 내가 지웠다면 단계와 붙은 선이 사라진다", () => {
  const c: ConflictItem = {
    kind: "node",
    node_id: "n2",
    field: "*",
    label: "다듬기",
    base: merged.nodes[1],
    mine: null,
    theirs: merged.nodes[1],
  };
  const out = applyChoices(merged, [c], { [conflictKey(c)]: "mine" });
  expect(out.nodes?.map((n) => n.id)).toEqual(["n1", "n3"]);
  expect(out.edges).toEqual([]);
});

test("내가 고친 단계를 상대가 지운 경우 '내 것'이면 단계가 되살아난다", () => {
  const without = { ...merged, nodes: merged.nodes.filter((n) => n.id !== "n2") };
  const mine = { id: "n2", type: "template", data: { template: "내 글" } };
  const c: ConflictItem = {
    kind: "node",
    node_id: "n2",
    field: "*",
    label: "다듬기",
    base: merged.nodes[1],
    mine,
    theirs: null,
  };
  const out = applyChoices(without, [c], { [conflictKey(c)]: "mine" });
  expect(out.nodes?.find((n) => n.id === "n2")?.data?.template).toBe("내 글");
});

test("값(변수) 충돌과 칸 지우기", () => {
  const v: ConflictItem = {
    kind: "variable",
    node_id: "a",
    field: "*",
    label: "a",
    base: 1,
    mine: 9,
    theirs: 5,
  };
  const gone: ConflictItem = {
    kind: "node",
    node_id: "n3",
    field: "data.template",
    label: "n3",
    base: "x",
    mine: null,
    theirs: "끝",
  };
  const choices: Choices = { [conflictKey(v)]: "mine", [conflictKey(gone)]: "mine" };
  const out = applyChoices(merged, [v, gone], choices);
  expect(out.variables).toEqual({ a: 9 });
  expect(out.nodes?.find((n) => n.id === "n3")?.data).toEqual({});
});

test("모두 골랐는지, 단계별로 묶기", () => {
  const other: ConflictItem = { ...fieldConflict, field: "data.label", label: "다듬기" };
  expect(allChosen([fieldConflict, other], { [conflictKey(fieldConflict)]: "mine" })).toBe(false);
  expect(allChosen([fieldConflict, other], defaultChoices([fieldConflict, other]))).toBe(true);
  const groups = groupConflicts([fieldConflict, other]);
  expect(groups).toHaveLength(1);
  expect(groups[0]?.items).toHaveLength(2);
});

test("화면 문구: 칸 이름과 값은 JSON 대신 읽기 쉽게", () => {
  expect(fieldLabel({ kind: "node", field: "data.template" })).toBe("글 틀");
  expect(fieldLabel({ kind: "node", field: "*" })).toBe("단계 전체");
  expect(fieldLabel({ kind: "node", field: "data.custom_key" })).toBe("custom_key");
  expect(fieldLabel({ kind: "variable", field: "*" })).toBe("값");
  expect(valueText(null)).toBe("(없음·지움)");
  expect(valueText("")).toBe("(빈 칸)");
  expect(valueText(true)).toBe("예");
  expect(valueText([1, 2, 3])).toBe("목록 3개");
  expect(valueText({ data: { label: "환율" } })).toBe("'환율' 단계");
  expect(valueText("가".repeat(300), 20)).toHaveLength(20);
});

test("남이 고친 단계 찾기와 같은 흐름 판단(순서·자리 무관은 아님, 내용 비교)", () => {
  const next = {
    ...merged,
    nodes: merged.nodes.map((n) => (n.id === "n3" ? { ...n, data: { template: "바뀜" } } : n)),
  };
  expect(changedNodeIds(merged, next)).toEqual(["n3"]);
  expect(changedNodeIds(merged, merged)).toEqual([]);
  expect(sameGraph(merged, { ...merged, nodes: [...merged.nodes].reverse() })).toBe(true);
  expect(sameGraph(merged, next)).toBe(false);
});
