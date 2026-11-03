// 목록 위 도구 막대(검색·필터)와 아래 페이지 넘김(개수 선택). useListControls와 함께 쓴다.
import { ChevronLeft, ChevronRight, Search, X } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { PAGE_SIZES, type ListControls } from "@/lib/useListControls";

const fieldCls =
  "h-9 rounded-lg border border-slate-300 bg-white text-sm text-slate-800 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/15";

export function ListToolbar<T>({
  c,
  placeholder = "검색",
  className,
  children,
}: {
  c: ListControls<T>;
  placeholder?: string;
  className?: string;
  /** 오른쪽에 붙일 추가 버튼 등 */
  children?: ReactNode;
}) {
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)} role="search">
      <div className="relative min-w-[160px] flex-1 sm:max-w-xs">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          type="search"
          value={c.query}
          onChange={(e) => c.setQuery(e.target.value)}
          placeholder={placeholder}
          aria-label={placeholder}
          className={cn(fieldCls, "w-full pl-8 pr-8 [&::-webkit-search-cancel-button]:hidden")}
        />
        {c.query && (
          <button
            type="button"
            onClick={() => c.setQuery("")}
            aria-label="검색어 지우기"
            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {c.filters.map((f) => (
        <select
          key={f.id}
          aria-label={f.label}
          value={c.filterValues[f.id] ?? ""}
          onChange={(e) => c.setFilter(f.id, e.target.value)}
          className={cn(
            fieldCls,
            "max-w-[11rem] px-2",
            c.filterValues[f.id] && "border-indigo-400 bg-indigo-50 text-indigo-700",
          )}
        >
          <option value="">{f.label}: 전체</option>
          {f.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      ))}
      {c.active && (
        <button
          type="button"
          onClick={c.resetFilters}
          className="h-9 rounded-lg px-2 text-xs font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-800"
        >
          초기화
        </button>
      )}
      {children && <div className="ml-auto flex items-center gap-2">{children}</div>}
    </div>
  );
}

/** 목록 아래: 결과 수, 한 번에 볼 개수, 페이지 넘김 */
export function ListPager<T>({ c, className }: { c: ListControls<T>; className?: string }) {
  const from = c.total === 0 ? 0 : (c.page - 1) * c.size + 1;
  const to = Math.min(c.page * c.size, c.total);
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500",
        className,
      )}
    >
      <span>{c.total === 0 ? "0개" : `${c.total.toLocaleString()}개 중 ${from}–${to}`}</span>
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1">
          <span className="sr-only sm:not-sr-only">한 번에</span>
          <select
            aria-label="한 번에 볼 개수"
            value={c.size}
            onChange={(e) => c.setSize(Number(e.target.value))}
            className="h-8 rounded-md border border-slate-300 bg-white px-1.5 text-xs text-slate-700 focus:border-indigo-500 focus:outline-none"
          >
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n}개
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-center">
          <button
            type="button"
            onClick={() => c.setPage(c.page - 1)}
            disabled={c.page <= 1}
            aria-label="이전 페이지"
            className="rounded-md p-1.5 hover:bg-slate-100 disabled:opacity-30 disabled:hover:bg-transparent"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="min-w-[3.5rem] text-center tabular-nums">
            {c.page} / {c.pages}
          </span>
          <button
            type="button"
            onClick={() => c.setPage(c.page + 1)}
            disabled={c.page >= c.pages}
            aria-label="다음 페이지"
            className="rounded-md p-1.5 hover:bg-slate-100 disabled:opacity-30 disabled:hover:bg-transparent"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

/** 검색·필터 결과가 없을 때 */
export function NoMatch<T>({ c }: { c: ListControls<T> }) {
  if (c.total > 0 || !c.active) return null;
  return (
    <div className="px-4 py-8 text-center text-sm text-slate-500">
      찾는 항목이 없어요.
      <br />
      <button
        type="button"
        onClick={c.resetFilters}
        className="mt-1 font-medium text-indigo-600 hover:underline"
      >
        검색어와 필터를 지우고 다시 보기
      </button>
    </div>
  );
}
