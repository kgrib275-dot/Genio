import {
  autocompleteAt,
  completeAt,
  filterOptions,
  flatOptions,
  insertAt,
  refsIn,
  removeRef,
  toDisplay,
  toRaw,
  upstreamIds,
  valueGroups,
  wantsPicker,
  type RefEdge,
  type RefNode,
} from "@/components/canvas/valueRefs";

const nodes: RefNode[] = [
  {
    id: "n1",
    type: "input",
    data: { label: "사용자 입력", fields: [{ key: "message", label: "메시지" }] },
  },
  {
    id: "n3",
    type: "llm",
    data: {
      label: "분류",
      output_schema: { properties: { category: { type: "string", title: "분류 결과" } } },
    },
  },
  { id: "n4", type: "http", data: { label: "조회" } },
  { id: "n2", type: "output", data: { label: "결과" } },
  { id: "n9", type: "llm", data: { label: "떨어진 단계" } },
];
const edges: RefEdge[] = [
  { source: "n1", target: "n3" },
  { source: "n3", target: "n4" },
  { source: "n4", target: "n2" },
];
const specs = [
  { type: "http", label: "HTTP", output_schema: { properties: { status: {}, body: {} } } },
];

test("앞 단계만 값 목록에 나온다", () => {
  expect([...upstreamIds("n4", edges)].sort()).toEqual(["n1", "n3"]);
  const groups = valueGroups(nodes, edges, specs, "n2", { company: "효성" });
  expect(groups.map((g) => g.label)).toEqual(["사용자 입력", "분류", "조회", "흐름 값"]);
  const opts = flatOptions(groups);
  expect(opts.map((o) => o.expr)).toEqual([
    "n1.message",
    "n3.text",
    "n3.category",
    "n4.status",
    "n4.body",
    "vars.company",
  ]);
  expect(opts[0]?.label).toBe("사용자 입력 › 메시지");
  expect(opts[2]?.label).toBe("분류 › 분류 결과");
  expect(opts.some((o) => o.expr.startsWith("n9."))).toBe(false);
});

test("{{ }} ↔ 읽기 쉬운 표시를 오가도 원래 값이 그대로다", () => {
  const opts = flatOptions(valueGroups(nodes, edges, specs, "n2"));
  const raw = "문의: {{n1.message}} / 분류 {{ n3.category }} / 모름 {{x.y | upper}}";
  const shown = toDisplay(raw, opts);
  expect(shown).toBe(
    "문의: «사용자 입력 › 메시지» / 분류 «분류 › 분류 결과» / 모름 {{x.y | upper}}",
  );
  expect(toRaw(shown, opts)).toBe(
    "문의: {{n1.message}} / 분류 {{n3.category}} / 모름 {{x.y | upper}}",
  );
  expect(toRaw("«없는 값»", opts)).toBe("«없는 값»");
  expect(refsIn(raw, opts)).toEqual([
    { expr: "n1.message", label: "사용자 입력 › 메시지" },
    { expr: "n3.category", label: "분류 › 분류 결과" },
    { expr: "x.y | upper", label: null },
  ]);
  expect(removeRef(raw, "n1.message")).toBe(
    "문의:  / 분류 {{ n3.category }} / 모름 {{x.y | upper}}",
  );
});

test("커서에 끼워 넣기와 자동완성", () => {
  expect(insertAt("안녕 !", 3, 3, "{{n1.message}}")).toEqual({
    text: "안녕 {{n1.message}}!",
    cursor: 17,
  });
  const text = "결과: {{분류";
  const ac = autocompleteAt(text, text.length);
  expect(ac).toEqual({ start: 4, query: "분류" });
  const opts = flatOptions(valueGroups(nodes, edges, specs, "n2"));
  expect(filterOptions(opts, "분류").map((o) => o.expr)).toEqual(["n3.text", "n3.category"]);
  expect(completeAt(text, 4, text.length, "n3.category").text).toBe("결과: {{n3.category}}");
  expect(autocompleteAt("끝난 {{n1.message}} 뒤", 18)).toBeNull();
});

test("이름·종류 칸에는 버튼을 달지 않는다", () => {
  expect(wantsPicker("root_prompt")).toBe(true);
  expect(wantsPicker("root_cases_0_when")).toBe(true);
  expect(wantsPicker("root_label")).toBe(false);
  expect(wantsPicker("root_fields_0_key")).toBe(false);
});
