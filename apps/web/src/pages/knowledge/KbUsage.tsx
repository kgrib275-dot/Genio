// v0.8 지식 사용 한도: 문서 수·전체 크기 사용량을 보여 주고, 소유자·관리자는 한도를 바꾼다.
import { Gauge } from "lucide-react";
import { useState } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import {
  usagePercent,
  useKbUsage,
  useSetKbLimits,
  type KbLimits,
  type KbUsage,
} from "@/lib/api/v8kb";
import { cn, formatBytes } from "@/lib/cn";

function Meter({
  label,
  used,
  limit,
  text,
}: {
  label: string;
  used: number;
  limit: number;
  text: string;
}) {
  const pct = usagePercent(used, limit);
  return (
    <div className="min-w-[9rem] flex-1" title={`${label}: ${text}`}>
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-slate-500">{label}</span>
        <span
          className={cn(
            "font-medium",
            pct != null && pct >= 90 ? "text-red-600" : "text-slate-700",
          )}
        >
          {text}
        </span>
      </div>
      <div
        className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100"
        role="progressbar"
        aria-label={`${label} 사용량`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct ?? 0}
      >
        <div
          className={cn(
            "h-full rounded-full transition-all",
            pct != null && pct >= 90
              ? "bg-red-500"
              : pct != null && pct >= 70
                ? "bg-amber-500"
                : "bg-indigo-500",
          )}
          style={{ width: `${pct ?? 0}%` }}
        />
      </div>
    </div>
  );
}

function LimitsDialog({ ws, data, onClose }: { ws: string; data: KbUsage; onClose: () => void }) {
  const set = useSetKbLimits(ws);
  const [v, setV] = useState<KbLimits>(data.limits);
  const field = (key: keyof KbLimits, hint: string) => (
    <Field label={data.labels[key]} htmlFor={`lim-${key}`} hint={hint}>
      <Input
        id={`lim-${key}`}
        type="number"
        min={0}
        value={v[key]}
        onChange={(e) => setV({ ...v, [key]: Math.max(0, Number(e.target.value) || 0) })}
      />
    </Field>
  );
  return (
    <Dialog
      open
      onClose={onClose}
      title="지식 사용 한도"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            취소
          </Button>
          <Button
            disabled={set.isPending}
            onClick={() =>
              set.mutate(v, {
                onSuccess: () => {
                  toast.success("한도를 바꿨어요.");
                  onClose();
                },
              })
            }
          >
            저장
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <p className="text-slate-600">
          워크스페이스 전체의 한도예요. 0을 넣으면 제한이 없어요. 이미 있는 문서는 그대로 두고,
          한도를 넘는 새 문서만 막아요.
        </p>
        {field("max_documents", "지식베이스 전체의 문서 개수")}
        {field("max_total_mb", "올린 문서 크기의 합(MB)")}
        {field("max_writes_per_min", "한 번에 너무 많이 올리거나 가져오는 것을 막아요")}
        <ErrorBox error={set.error} />
      </div>
    </Dialog>
  );
}

export function UsageBar({ ws }: { ws: string }) {
  const usage = useKbUsage(ws);
  const [open, setOpen] = useState(false);
  const d = usage.data;
  if (!d) return null;
  const mb = d.limits.max_total_mb;
  return (
    <div
      className="mb-4 flex flex-wrap items-end gap-x-6 gap-y-2 rounded-xl border border-slate-200 bg-white px-4 py-3"
      aria-label="지식 사용량"
    >
      <Meter
        label="문서"
        used={d.usage.documents}
        limit={d.limits.max_documents}
        text={`${d.usage.documents.toLocaleString()}개${d.limits.max_documents ? ` / ${d.limits.max_documents.toLocaleString()}개` : " (제한 없음)"}`}
      />
      <Meter
        label="전체 크기"
        used={d.usage.bytes}
        limit={mb * 1024 * 1024}
        text={`${formatBytes(d.usage.bytes)}${mb ? ` / ${mb.toLocaleString()}MB` : " (제한 없음)"}`}
      />
      <div className="ml-auto flex items-center gap-2 text-xs text-slate-500">
        {d.limits.max_writes_per_min > 0 && (
          <span>분당 올리기 {d.limits.max_writes_per_min}번까지</span>
        )}
        {d.can_edit && (
          <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
            <Gauge className="h-3.5 w-3.5" /> 한도 바꾸기
          </Button>
        )}
      </div>
      {open && <LimitsDialog ws={ws} data={d} onClose={() => setOpen(false)} />}
    </div>
  );
}
