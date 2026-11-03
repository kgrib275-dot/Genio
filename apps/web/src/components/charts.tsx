import type { ReactNode } from "react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";

export function StatTile({
  label,
  value,
  sub,
  icon,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-xs text-slate-500">
        {icon}
        {label}
      </div>
      <p className="mt-1.5 text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">{value}</p>
      {sub && <p className="mt-0.5 text-[11px] text-slate-400">{sub}</p>}
    </Card>
  );
}

export interface SeriesPoint {
  label: string;
  value: number;
}

function shortDate(label: string): string {
  const m = /^\d{4}-(\d{2})-(\d{2})/.exec(label);
  return m ? `${Number(m[1])}/${Number(m[2])}` : label;
}

/** 막대그래프(SVG). 값이 모두 0이어도 바닥선이 보이게 그린다. */
export function BarChart({
  data,
  format = (v) => v.toLocaleString(),
  tone = "indigo",
  height = 140,
}: {
  data: SeriesPoint[];
  format?: (v: number) => string;
  tone?: "indigo" | "emerald" | "amber" | "sky" | "rose";
  height?: number;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const fill = {
    indigo: "fill-indigo-500",
    emerald: "fill-emerald-500",
    amber: "fill-amber-500",
    sky: "fill-sky-500",
    rose: "fill-rose-500",
  }[tone];
  const n = Math.max(1, data.length);
  const w = 100 / n;
  return (
    <div>
      <svg
        viewBox={`0 0 100 ${height}`}
        preserveAspectRatio="none"
        className="w-full"
        style={{ height }}
        role="img"
        aria-label="막대그래프"
      >
        <line
          x1="0"
          x2="100"
          y1={height - 0.5}
          y2={height - 0.5}
          className="stroke-slate-200"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
        {data.map((d, i) => {
          const h = (d.value / max) * (height - 8);
          return (
            <rect
              key={i}
              x={i * w + w * 0.18}
              width={w * 0.64}
              y={height - h}
              height={Math.max(h, d.value > 0 ? 1.5 : 0)}
              rx="0.8"
              className={cn(fill, "opacity-85")}
            >
              <title>{`${d.label}: ${format(d.value)}`}</title>
            </rect>
          );
        })}
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-slate-400">
        <span>{data[0] ? shortDate(data[0].label) : ""}</span>
        <span>
          {data.length > 2 ? shortDate(data[Math.floor(data.length / 2)]?.label ?? "") : ""}
        </span>
        <span>{data.length > 1 ? shortDate(data[data.length - 1]?.label ?? "") : ""}</span>
      </div>
    </div>
  );
}

/** 꺾은선그래프(SVG) */
export function LineChart({
  data,
  height = 140,
  max: fixedMax,
  format = (v) => v.toLocaleString(),
}: {
  data: SeriesPoint[];
  height?: number;
  max?: number;
  format?: (v: number) => string;
}) {
  const max = fixedMax ?? Math.max(1, ...data.map((d) => d.value));
  const n = data.length;
  const x = (i: number) => (n <= 1 ? 50 : (i / (n - 1)) * 100);
  const y = (v: number) => height - 4 - (v / max) * (height - 12);
  const path = data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(d.value)}`).join(" ");
  const area = n ? `${path} L${x(n - 1)},${height} L${x(0)},${height} Z` : "";
  return (
    <div>
      <svg
        viewBox={`0 0 100 ${height}`}
        preserveAspectRatio="none"
        className="w-full"
        style={{ height }}
        role="img"
        aria-label="꺾은선그래프"
      >
        <line
          x1="0"
          x2="100"
          y1={height - 0.5}
          y2={height - 0.5}
          className="stroke-slate-200"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
        {n > 0 && <path d={area} className="fill-indigo-500/10" />}
        {n > 0 && (
          <path
            d={path}
            className="fill-none stroke-indigo-500"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
        )}
        {data.map((d, i) => (
          <circle key={i} cx={x(i)} cy={y(d.value)} r="1.2" className="fill-indigo-600">
            <title>{`${d.label}: ${format(d.value)}`}</title>
          </circle>
        ))}
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-slate-400">
        <span>{data[0] ? shortDate(data[0].label) : ""}</span>
        <span>{n > 1 ? shortDate(data[n - 1]?.label ?? "") : ""}</span>
      </div>
    </div>
  );
}

export function ChartCard({
  title,
  value,
  children,
}: {
  title: string;
  value?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <p className="text-sm font-semibold text-slate-700">{title}</p>
        {value !== undefined && <p className="text-sm font-bold text-slate-900">{value}</p>}
      </div>
      {children}
    </Card>
  );
}
