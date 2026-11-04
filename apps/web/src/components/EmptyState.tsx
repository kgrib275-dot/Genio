// v0.6 빈 화면 안내: 무엇이 들어가는 곳인지 + 다음에 할 일(버튼) 하나. 모든 목록이 함께 쓴다.
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/cn";

export interface EmptyAction {
  label: string;
  /** 화면 이동(둘 중 하나) */
  to?: string;
  onClick?: () => void;
  icon?: ReactNode;
}

const PRIMARY =
  "inline-flex h-9 items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 text-sm font-medium text-white hover:bg-indigo-500";
const SECONDARY =
  "inline-flex h-9 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3.5 text-sm text-slate-700 hover:bg-slate-50";

function ActionButton({ a, primary }: { a: EmptyAction; primary: boolean }) {
  const cls = primary ? PRIMARY : SECONDARY;
  if (a.to)
    return (
      <Link to={a.to} className={cls}>
        {a.icon}
        {a.label}
      </Link>
    );
  return (
    <button type="button" onClick={a.onClick} className={cls}>
      {a.icon}
      {a.label}
    </button>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  secondary,
  compact = false,
  className,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: EmptyAction | null;
  secondary?: EmptyAction | null;
  /** 카드 안처럼 좁은 곳: 위아래 여백을 줄이고 테두리 없이 */
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      role="status"
      className={cn(
        "flex flex-col items-center gap-2 text-center text-sm",
        compact
          ? "px-5 py-8"
          : "rounded-xl border border-dashed border-slate-300 bg-white/60 px-6 py-12",
        className,
      )}
    >
      {icon && (
        <span className="mb-1 inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-500">
          {icon}
        </span>
      )}
      <p className="font-semibold text-slate-800">{title}</p>
      {description && <p className="max-w-md text-slate-500">{description}</p>}
      {(action || secondary) && (
        <div className="mt-2 flex flex-wrap justify-center gap-2">
          {action && <ActionButton a={action} primary />}
          {secondary && <ActionButton a={secondary} primary={false} />}
        </div>
      )}
    </div>
  );
}
