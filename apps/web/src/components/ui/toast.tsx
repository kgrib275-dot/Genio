import { useToasts } from "@/components/ui/toast-store";
import { cn } from "@/lib/cn";

export function Toaster() {
  const { items, dismiss } = useToasts();
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2">
      {items.map((t) => (
        <div
          key={t.id}
          role={t.tone === "error" ? "alert" : "status"}
          className={cn(
            "pointer-events-auto rounded-md border px-4 py-3 text-sm shadow-lg",
            t.tone === "error" && "border-red-200 bg-red-50 text-red-900",
            t.tone === "success" && "border-emerald-200 bg-emerald-50 text-emerald-900",
            t.tone === "info" && "border-slate-200 bg-white text-slate-900",
          )}
          onClick={() => dismiss(t.id)}
        >
          <p className="font-medium">{t.message}</p>
          {t.hint && <p className="mt-0.5 text-xs opacity-80">{t.hint}</p>}
        </div>
      ))}
    </div>
  );
}
