import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-xl border border-slate-200/80 bg-white shadow-card", className)}
      {...props}
    />
  );
}

export function CardHeader({
  title,
  description,
  action,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-5 pb-3 pt-5">
      <div>
        <h2 className="text-[15px] font-semibold text-slate-900">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-slate-500">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-4 pb-5 pt-1 sm:px-5", className)} {...props} />;
}

export function PageHeader({
  title,
  description,
  action,
  help,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  /** 제목 옆에 붙는 '?' 도움말 버튼 */
  help?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="flex items-center gap-1.5 text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">
          {title}
          {help}
        </h1>
        {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function Empty({ children, icon }: { children: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-slate-300 bg-white/60 px-6 py-12 text-center text-sm text-slate-500">
      {icon && <div className="text-slate-300">{icon}</div>}
      {children}
    </div>
  );
}
