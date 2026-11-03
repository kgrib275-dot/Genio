import { sortItems } from "@/lib/marketSort";

const items = [
  { name: "노션", installs: 3, version: "1.0.0" },
  { name: "가나다", installs: 10, version: "1.10.0" },
  { name: "슬랙", installs: 3, version: "1.2.0" },
];

test("마켓 목록을 설치 수·이름·버전 순으로 정렬한다", () => {
  expect(sortItems(items, "popular")?.map((i) => i.name)).toEqual(["가나다", "노션", "슬랙"]);
  expect(sortItems(items, "name")?.map((i) => i.name)).toEqual(["가나다", "노션", "슬랙"]);
  expect(sortItems(items, "new")?.map((i) => i.version)).toEqual(["1.10.0", "1.2.0", "1.0.0"]);
  expect(items[0]?.name).toBe("노션");
  expect(sortItems(undefined, "name")).toBeUndefined();
});
