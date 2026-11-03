import { act, renderHook } from "@testing-library/react";
import { useListControls } from "@/lib/useListControls";

type Item = { name: string; kind: string };
const items: Item[] = Array.from({ length: 25 }, (_, i) => ({
  name: `항목 ${i + 1}`,
  kind: i % 2 ? "홀" : "짝",
}));

test("검색·필터·개수·페이지", () => {
  window.localStorage.clear();
  const { result } = renderHook(() =>
    useListControls(items, {
      key: "t",
      defaultSize: 10,
      search: (i) => i.name,
      filters: [
        {
          id: "kind",
          label: "종류",
          options: [
            { value: "짝", label: "짝" },
            { value: "홀", label: "홀" },
          ],
          match: (i, v) => i.kind === v,
        },
      ],
    }),
  );
  expect(result.current.total).toBe(25);
  expect(result.current.pages).toBe(3);
  expect(result.current.pageItems).toHaveLength(10);

  act(() => result.current.setPage(3));
  expect(result.current.pageItems).toHaveLength(5);

  // 검색하면 1페이지로
  act(() => result.current.setQuery("항목 1"));
  expect(result.current.page).toBe(1);
  expect(result.current.total).toBe(11); // 1, 10~19
  expect(result.current.active).toBe(true);

  act(() => result.current.setFilter("kind", "짝"));
  expect(result.current.filtered.every((i) => i.kind === "짝")).toBe(true);

  act(() => result.current.resetFilters());
  expect(result.current.total).toBe(25);

  // 개수는 기억한다
  act(() => result.current.setSize(50));
  expect(result.current.pages).toBe(1);
  expect(window.localStorage.getItem("genio.list.t.size")).toBe("50");
});
