// 모든 목록이 함께 쓰는 검색·필터·개수(페이지 크기)·페이지 상태.
// 페이지 크기는 목록마다 브라우저에 기억한다(기억 못 해도 기본값으로 동작).
import { useEffect, useMemo, useState } from "react";

export const PAGE_SIZES = [10, 20, 50, 100] as const;

export interface FilterOption {
  value: string;
  label: string;
}

export interface FilterDef<T> {
  id: string;
  /** 필터 칸 이름(예: "상태") */
  label: string;
  options: FilterOption[];
  /** 고른 값(value)에 맞는 항목인지. 값이 ""(전체)면 부르지 않는다. */
  match: (item: T, value: string) => boolean;
}

export interface ListControls<T> {
  query: string;
  setQuery: (q: string) => void;
  filters: FilterDef<T>[];
  filterValues: Record<string, string>;
  setFilter: (id: string, value: string) => void;
  resetFilters: () => void;
  page: number;
  setPage: (p: number) => void;
  size: number;
  setSize: (n: number) => void;
  total: number;
  pages: number;
  /** 검색·필터를 적용한 전체 */
  filtered: T[];
  /** 지금 페이지에 보여 줄 항목 */
  pageItems: T[];
  active: boolean;
}

function readSize(key: string, fallback: number): number {
  try {
    const n = Number(window.localStorage.getItem(`genio.list.${key}.size`));
    return (PAGE_SIZES as readonly number[]).includes(n) ? n : fallback;
  } catch {
    return fallback;
  }
}

function writeSize(key: string, n: number) {
  try {
    window.localStorage.setItem(`genio.list.${key}.size`, String(n));
  } catch {
    // 기억하지 못해도 동작에는 문제없다
  }
}

/** 한글 대소문자·공백 차이를 무시하고 비교하기 위한 정규화 */
export function norm(s: string): string {
  return s.normalize("NFC").toLowerCase().replace(/\s+/g, " ").trim();
}

export function useListControls<T>(
  items: T[] | undefined,
  opts: {
    /** 페이지 크기를 기억할 이름(목록마다 다르게) */
    key: string;
    /** 검색할 글(여러 칸을 이어 붙여 돌려주면 된다) */
    search?: (item: T) => string;
    filters?: FilterDef<T>[];
    defaultSize?: number;
  },
): ListControls<T> {
  const filters = opts.filters ?? [];
  const [query, setQueryState] = useState("");
  const [filterValues, setFilterValues] = useState<Record<string, string>>({});
  const [page, setPage] = useState(1);
  const [size, setSizeState] = useState(() => readSize(opts.key, opts.defaultSize ?? 20));

  const filtered = useMemo(() => {
    const list = items ?? [];
    const q = norm(query);
    return list.filter((it) => {
      if (q && opts.search && !norm(opts.search(it)).includes(q)) return false;
      for (const f of filters) {
        const v = filterValues[f.id];
        if (v && !f.match(it, v)) return false;
      }
      return true;
    });
    // filters·search는 매번 새로 만들어져도 내용이 같다고 본다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, query, filterValues]);

  const pages = Math.max(1, Math.ceil(filtered.length / size));
  // 검색 결과가 줄어 지금 페이지가 사라지면 마지막 페이지로
  useEffect(() => {
    if (page > pages) setPage(pages);
  }, [page, pages]);
  const cur = Math.min(page, pages);
  const pageItems = filtered.slice((cur - 1) * size, cur * size);

  return {
    query,
    setQuery: (q) => {
      setQueryState(q);
      setPage(1);
    },
    filters,
    filterValues,
    setFilter: (id, value) => {
      setFilterValues((fv) => ({ ...fv, [id]: value }));
      setPage(1);
    },
    resetFilters: () => {
      setFilterValues({});
      setQueryState("");
      setPage(1);
    },
    page: cur,
    setPage,
    size,
    setSize: (n) => {
      setSizeState(n);
      writeSize(opts.key, n);
      setPage(1);
    },
    total: filtered.length,
    pages,
    filtered,
    pageItems,
    active: query.trim() !== "" || Object.values(filterValues).some(Boolean),
  };
}

/** 목록에서 값들을 모아 필터 선택지로 만든다(중복 제거, 가나다순). */
export function optionsFrom<T>(
  items: T[] | undefined,
  pick: (item: T) => string | null | undefined,
  label?: (value: string) => string,
): FilterOption[] {
  const set = new Set<string>();
  for (const it of items ?? []) {
    const v = pick(it);
    if (v) set.add(v);
  }
  return [...set]
    .sort((a, b) => a.localeCompare(b, "ko"))
    .map((v) => ({ value: v, label: label ? label(v) : v }));
}
