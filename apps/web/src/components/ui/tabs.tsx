import { useEffect, useRef } from "react";
import { cn } from "@/lib/cn";

/** 알약 모양 탭(세그먼트). 좁은 화면에서는 글자가 세로로 꺾이지 않고 옆으로 밀어서 본다. */
export function Tabs<T extends string>({
  value,
  onChange,
  items,
}: {
  value: T;
  onChange: (v: T) => void;
  items: { value: T; label: string }[];
}) {
  const listRef = useRef<HTMLDivElement>(null);
  // 고른 탭이 화면 밖에 있으면 보이는 자리로 옮긴다
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]');
    el?.scrollIntoView?.({ block: "nearest", inline: "center" });
  }, [value]);
  return (
    <div
      ref={listRef}
      role="tablist"
      className="mb-5 inline-flex max-w-full gap-1 overflow-x-auto rounded-lg bg-slate-100 p-1"
    >
      {items.map((it) => (
        <button
          key={it.value}
          type="button"
          role="tab"
          aria-selected={value === it.value}
          onClick={() => onChange(it.value)}
          className={cn(
            "shrink-0 whitespace-nowrap rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors",
            value === it.value
              ? "bg-white text-slate-900 shadow-sm"
              : "text-slate-500 hover:text-slate-800",
          )}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}
