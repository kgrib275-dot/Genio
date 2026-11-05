import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";

const PALETTE = [
  "from-indigo-500 to-violet-500",
  "from-sky-500 to-cyan-500",
  "from-emerald-500 to-teal-500",
  "from-amber-500 to-orange-500",
  "from-rose-500 to-pink-500",
  "from-fuchsia-500 to-purple-500",
];

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

/** 앱마다 이름으로 색을 정한 둥근 아이콘. 이모지 아이콘이 있으면 그것을 쓴다. */
export function AppIcon({
  name,
  icon,
  size = "md",
  logoUrl,
}: {
  name: string;
  icon?: string | null;
  size?: "sm" | "md" | "lg";
  /** v0.8 웹앱 로고(올린 그림 주소). 불러오지 못하면 기본 아이콘을 쓴다 */
  logoUrl?: string | null;
}) {
  const dims = { sm: "h-7 w-7 text-sm", md: "h-10 w-10 text-lg", lg: "h-12 w-12 text-xl" }[size];
  const emoji = icon && icon !== "🤖" ? icon : null;
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [logoUrl]);
  if (logoUrl && !broken)
    return (
      <img
        src={logoUrl}
        alt=""
        onError={() => setBroken(true)}
        className={cn(
          "inline-block shrink-0 rounded-xl border border-slate-200 bg-white object-contain p-0.5",
          dims,
        )}
      />
    );
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-xl bg-gradient-to-br font-semibold text-white shadow-sm",
        PALETTE[hash(name) % PALETTE.length],
        dims,
      )}
    >
      {emoji ?? (name.trim()[0] ?? "앱").toUpperCase()}
    </span>
  );
}

export function Avatar({ name }: { name: string }) {
  return (
    <span
      aria-hidden
      className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold text-slate-700"
    >
      {name.trim().slice(-2) || "?"}
    </span>
  );
}
