// 자동 실행 화면들이 함께 쓰는 작은 부품(켜고 끄는 스위치, 복사 상자, 비밀값 한 번만 보여 주기)
import { Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast-store";
import { cn, copyText } from "@/lib/cn";

export function SecretOnce({ secret, onDone }: { secret: string; onDone?: () => void }) {
  return (
    <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-3">
      <p className="text-xs font-medium text-amber-900">
        서명 비밀값이에요. 이 창을 닫으면 다시 볼 수 없어요. 보내는 쪽 서비스에 저장해 두세요.
      </p>
      <CopyBox text={secret} label="비밀값" />
      {onDone && (
        <Button size="sm" onClick={onDone}>
          저장해 뒀어요
        </Button>
      )}
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50",
        checked ? "bg-indigo-600" : "bg-slate-300",
      )}
    >
      <span
        className={cn(
          "inline-block h-4 w-4 rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-4" : "translate-x-0.5",
        )}
      />
    </button>
  );
}

export function CopyBox({ text, label }: { text: string; label: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 p-2">
      <code className="min-w-0 flex-1 whitespace-pre-wrap break-all font-mono text-[11px] text-slate-700">
        {text}
      </code>
      <Button
        size="sm"
        variant="ghost"
        aria-label={`${label} 복사`}
        title={`${label} 복사`}
        onClick={async () => {
          if (await copyText(text)) toast.success(`${label}를 복사했어요.`);
        }}
      >
        <Copy className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
