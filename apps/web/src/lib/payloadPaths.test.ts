import { filterPaths, flattenPaths } from "@/lib/payloadPaths";

const body = {
  action: "opened",
  issue: { title: "로그인이 안 돼요", labels: [{ name: "bug" }, { name: "ui" }], empty: {} },
  zero: 0,
  flag: false,
  nothing: null,
};

test("끝 위치와 예시 값을 모은다(목록은 [번호], 빈 값은 건너뜀)", () => {
  const items = flattenPaths(body);
  const map = Object.fromEntries(items.map((i) => [i.path, i.sample]));
  expect(map["action"]).toBe("opened");
  expect(map["issue.title"]).toBe("로그인이 안 돼요");
  expect(map["issue.labels[0].name"]).toBe("bug");
  expect(map["issue.labels[1].name"]).toBe("ui");
  expect(map["zero"]).toBe("0");
  expect(map["flag"]).toBe("false");
  expect("nothing" in map).toBe(false);
  expect("issue.empty" in map).toBe(false);
});

test("목록은 앞 5개만, 긴 글은 줄이고, 개수 한도를 지킨다", () => {
  const items = flattenPaths({ a: Array.from({ length: 9 }, (_, i) => i), t: "가".repeat(100) });
  expect(items.filter((i) => i.path.startsWith("a[")).length).toBe(5);
  expect(items.find((i) => i.path === "t")?.sample.length).toBe(60);
  const many = Object.fromEntries(Array.from({ length: 200 }, (_, i) => [`k${i}`, i]));
  expect(flattenPaths(many, 10)).toHaveLength(10);
});

test("검색은 위치와 예시 값 모두에서 찾는다", () => {
  const items = flattenPaths(body);
  expect(filterPaths(items, "TITLE").map((i) => i.path)).toEqual(["issue.title"]);
  expect(filterPaths(items, "bug").map((i) => i.path)).toEqual(["issue.labels[0].name"]);
  expect(filterPaths(items, "")).toHaveLength(items.length);
});
