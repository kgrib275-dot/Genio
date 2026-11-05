import {
  DEFAULT_TRIGGERS,
  MAX_LINKS,
  addLink,
  chainProblem,
  cooldownText,
  moveLink,
  removeLink,
  setLinkModel,
  strategyLabel,
  type ChainLink,
} from "@/lib/llmChain";

const L = (id: string, model = ""): ChainLink => ({ provider_id: id, model });

test("순서를 한 칸씩 옮기고, 끝에서는 그대로 둔다", () => {
  const list = [L("a"), L("b"), L("c")];
  expect(moveLink(list, 1, -1).map((l) => l.provider_id)).toEqual(["b", "a", "c"]);
  expect(moveLink(list, 1, 1).map((l) => l.provider_id)).toEqual(["a", "c", "b"]);
  expect(moveLink(list, 0, -1)).toBe(list);
  expect(moveLink(list, 2, 1)).toBe(list);
  expect(moveLink(list, 9, 1)).toBe(list);
  // 원래 목록은 바뀌지 않는다
  expect(list.map((l) => l.provider_id)).toEqual(["a", "b", "c"]);
});

test("같은 연결은 한 번만, 최대 5곳까지 추가한다", () => {
  let list: ChainLink[] = [];
  list = addLink(list, "a");
  list = addLink(list, "a");
  expect(list).toHaveLength(1);
  expect(addLink(list, "")).toBe(list);
  for (const id of ["b", "c", "d", "e", "f", "g"]) list = addLink(list, id);
  expect(list).toHaveLength(MAX_LINKS);
  expect(list.some((l) => l.provider_id === "g")).toBe(false);
});

test("빼기와 모델 이름 바꾸기", () => {
  const list = [L("a"), L("b", "gpt-5")];
  expect(removeLink(list, 0).map((l) => l.provider_id)).toEqual(["b"]);
  expect(setLinkModel(list, 0, "m1")[0]?.model).toBe("m1");
  expect(setLinkModel(list, 0, "m1")[1]?.model).toBe("gpt-5");
});

test("저장 전 안내: 켰는데 비었거나 조건이 하나도 없으면 막는다", () => {
  expect(chainProblem(false, [], DEFAULT_TRIGGERS)).toBeNull();
  expect(chainProblem(true, [], DEFAULT_TRIGGERS)).toContain("하나 이상");
  const none = { ...DEFAULT_TRIGGERS, outage: false, rate_limit: false };
  expect(chainProblem(true, [L("a")], none)).toContain("조건");
  expect(chainProblem(true, [L("a")], DEFAULT_TRIGGERS)).toBeNull();
});

test("쉬는 시간과 방식 이름", () => {
  expect(cooldownText(0)).toBe("");
  expect(cooldownText(20)).toBe("20초");
  expect(cooldownText(75)).toBe("1분 15초");
  expect(cooldownText(120)).toBe("2분");
  expect(cooldownText(3600)).toBe("1시간 0분");
  expect(strategyLabel("round_robin")).toBe("돌아가며");
  expect(strategyLabel(undefined)).toBe("앞의 키부터");
});
