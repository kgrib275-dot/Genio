// 마켓 목록 정렬(v0.6 마켓 확대)
export type SortKey = "popular" | "name" | "new";
export const SORTS: { value: SortKey; label: string }[] = [
  { value: "popular", label: "많이 설치한 순" },
  { value: "name", label: "이름순" },
  { value: "new", label: "새로 나온 순" },
];

/** 마켓 목록 정렬(설치 수·이름·버전 순서). 원본은 바꾸지 않는다. */
export function sortItems<T extends { name: string; installs: number; version: string }>(
  list: T[] | undefined,
  sort: SortKey,
): T[] | undefined {
  if (!list) return list;
  const out = [...list];
  if (sort === "name") out.sort((a, b) => a.name.localeCompare(b.name, "ko"));
  else if (sort === "new")
    out.sort((a, b) => b.version.localeCompare(a.version, undefined, { numeric: true }));
  else out.sort((a, b) => b.installs - a.installs || a.name.localeCompare(b.name, "ko"));
  return out;
}
