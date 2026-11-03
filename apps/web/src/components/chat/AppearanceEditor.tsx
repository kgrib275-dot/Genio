// 배포 모양(위젯 색·위치·버튼 글·인사 말풍선·창 크기)을 바꾸고 바로 미리 본다.
import { MessageCircle, X } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import {
  appearanceOf,
  DEFAULT_APPEARANCE,
  HEX_COLOR,
  useUpdateAppearance,
  type Appearance,
} from "@/lib/api/chat";
import { cn } from "@/lib/cn";

const SWATCHES = ["#4f46e5", "#0ea5e9", "#10b981", "#f59e0b", "#e11d48", "#7c3aed", "#0f172a"];

function MiniPreview({
  look,
  widget,
  appName,
}: {
  look: Appearance;
  widget: boolean;
  appName: string;
}) {
  const side = look.position === "left" ? "left-3" : "right-3";
  return (
    <div
      aria-hidden
      className="relative h-60 overflow-hidden rounded-lg border border-slate-200 bg-gradient-to-b from-slate-50 to-slate-100"
      style={{ "--chat-accent": look.primary_color } as CSSProperties}
    >
      <div className="space-y-1.5 p-3">
        <div className="h-2 w-24 rounded bg-slate-200" />
        <div className="h-2 w-40 rounded bg-slate-200" />
        <div className="h-2 w-32 rounded bg-slate-200" />
      </div>
      {widget ? (
        <>
          <div
            className={cn(
              "absolute bottom-14 w-40 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg",
              side,
            )}
          >
            <div className="flex items-center gap-1 border-b border-slate-100 px-2 py-1.5 text-[10px] font-semibold text-slate-700">
              <span className="h-3 w-3 rounded bg-[color:var(--chat-accent)]" />
              <span className="truncate">{look.title || appName}</span>
            </div>
            <div className="space-y-1 p-2">
              <div className="ml-auto h-3 w-16 rounded-full bg-[color:var(--chat-accent)]" />
              <div className="h-3 w-24 rounded-full bg-slate-100" />
            </div>
          </div>
          {look.greeting && (
            <div
              className={cn(
                "absolute bottom-14 max-w-[9rem] translate-y-[-7.5rem] rounded-lg bg-white px-2 py-1.5 text-[10px] leading-snug text-slate-700 shadow-md",
                side,
              )}
            >
              {look.greeting}
            </div>
          )}
          <div
            className={cn(
              "absolute bottom-3 flex h-9 min-w-9 items-center justify-center gap-1 rounded-full bg-[color:var(--chat-accent)] px-2.5 text-[11px] font-semibold text-white shadow-md",
              side,
            )}
          >
            <MessageCircle className="h-4 w-4" />
            {look.launcher_text}
          </div>
        </>
      ) : (
        <div className="absolute inset-x-3 bottom-3 top-12 rounded-lg border border-slate-200 bg-white p-2 shadow">
          <p className="text-[10px] font-semibold text-slate-700">{look.title || appName}</p>
          <div className="mt-2 space-y-1">
            <div className="ml-auto h-3 w-20 rounded-full bg-[color:var(--chat-accent)]" />
            <div className="h-3 w-28 rounded-full bg-slate-100" />
          </div>
          <div className="absolute bottom-2 right-2 h-5 w-5 rounded-md bg-[color:var(--chat-accent)]" />
        </div>
      )}
    </div>
  );
}

export function AppearanceEditor({
  appId,
  deploymentId,
  initial,
  widget,
  appName,
  onClose,
}: {
  appId: string;
  deploymentId: string;
  initial: Partial<Appearance> | undefined;
  widget: boolean;
  appName: string;
  onClose: () => void;
}) {
  const [look, setLook] = useState<Appearance>(() => appearanceOf(initial));
  const [colorText, setColorText] = useState(look.primary_color);
  const save = useUpdateAppearance(appId);
  const set = <K extends keyof Appearance>(k: K, v: Appearance[K]) =>
    setLook((l) => ({ ...l, [k]: v }));
  const colorOk = HEX_COLOR.test(colorText);
  const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n || lo));

  return (
    <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50/60 p-3">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm font-semibold text-slate-800">
          {widget ? "위젯 모양" : "챗 화면 모양"}
        </p>
        <button
          type="button"
          onClick={onClose}
          aria-label="모양 바꾸기 닫기"
          className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="grid gap-4 md:grid-cols-[1fr_minmax(0,15rem)]">
        <div className="space-y-3">
          <Field label="대표 색" htmlFor={`color-${deploymentId}`}>
            <div className="flex flex-wrap items-center gap-2">
              <input
                id={`color-${deploymentId}`}
                type="color"
                value={look.primary_color}
                onChange={(e) => {
                  set("primary_color", e.target.value);
                  setColorText(e.target.value);
                }}
                className="h-9 w-10 cursor-pointer rounded border border-slate-300 bg-white p-0.5"
              />
              <Input
                aria-label="색 코드"
                className="w-28 font-mono"
                value={colorText}
                onChange={(e) => {
                  setColorText(e.target.value);
                  if (HEX_COLOR.test(e.target.value)) set("primary_color", e.target.value);
                }}
              />
              <div className="flex gap-1">
                {SWATCHES.map((c) => (
                  <button
                    key={c}
                    type="button"
                    aria-label={`색 ${c}`}
                    onClick={() => {
                      set("primary_color", c);
                      setColorText(c);
                    }}
                    className={cn(
                      "h-6 w-6 rounded-full border-2",
                      look.primary_color.toLowerCase() === c ? "border-slate-900" : "border-white",
                    )}
                    style={{ background: c }}
                  />
                ))}
              </div>
            </div>
            {!colorOk && (
              <p className="mt-1 text-xs text-red-600">
                색 코드가 맞지 않아요. #과 6자리(예: #4f46e5)로 적어 주세요.
              </p>
            )}
          </Field>
          <Field label="머리 제목(비우면 앱 이름)" htmlFor={`title-${deploymentId}`}>
            <Input
              id={`title-${deploymentId}`}
              maxLength={60}
              value={look.title}
              placeholder={appName}
              onChange={(e) => set("title", e.target.value)}
            />
          </Field>
          {widget && (
            <>
              <Field label="버튼 위치" htmlFor={`pos-${deploymentId}`}>
                <div
                  id={`pos-${deploymentId}`}
                  role="radiogroup"
                  className="inline-flex rounded-lg bg-slate-100 p-1"
                >
                  {(["left", "right"] as const).map((p) => (
                    <button
                      key={p}
                      type="button"
                      role="radio"
                      aria-checked={look.position === p}
                      onClick={() => set("position", p)}
                      className={cn(
                        "rounded-md px-3 py-1 text-sm",
                        look.position === p ? "bg-white font-medium shadow-sm" : "text-slate-500",
                      )}
                    >
                      {p === "left" ? "왼쪽 아래" : "오른쪽 아래"}
                    </button>
                  ))}
                </div>
              </Field>
              <Field label="버튼 글(비우면 아이콘만)" htmlFor={`launcher-${deploymentId}`}>
                <Input
                  id={`launcher-${deploymentId}`}
                  maxLength={20}
                  value={look.launcher_text}
                  placeholder="예: 무엇이든 물어보세요"
                  onChange={(e) => set("launcher_text", e.target.value)}
                />
              </Field>
              <Field label="인사 말풍선(3초 뒤 한 번)" htmlFor={`greet-${deploymentId}`}>
                <Textarea
                  id={`greet-${deploymentId}`}
                  maxLength={120}
                  rows={2}
                  value={look.greeting}
                  placeholder="예: 안녕하세요! 궁금한 점을 물어보세요."
                  onChange={(e) => set("greeting", e.target.value)}
                />
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="창 너비(300~640)" htmlFor={`w-${deploymentId}`}>
                  <Input
                    id={`w-${deploymentId}`}
                    type="number"
                    min={300}
                    max={640}
                    value={look.width}
                    onChange={(e) => set("width", Number(e.target.value))}
                    onBlur={() => set("width", clamp(look.width, 300, 640))}
                  />
                </Field>
                <Field label="창 높이(400~900)" htmlFor={`h-${deploymentId}`}>
                  <Input
                    id={`h-${deploymentId}`}
                    type="number"
                    min={400}
                    max={900}
                    value={look.height}
                    onChange={(e) => set("height", Number(e.target.value))}
                    onBlur={() => set("height", clamp(look.height, 400, 900))}
                  />
                </Field>
              </div>
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={look.open_on_load}
                  onChange={(e) => set("open_on_load", e.target.checked)}
                  className="accent-indigo-600"
                />
                페이지를 열면 챗 창도 바로 열기(넓은 화면만)
              </label>
            </>
          )}
        </div>
        <div>
          <p className="mb-1 text-xs font-medium text-slate-500">미리 보기</p>
          <MiniPreview look={look} widget={widget} appName={appName} />
        </div>
      </div>
      <ErrorBox error={save.error} />
      <div className="mt-3 flex flex-wrap justify-end gap-2">
        <Button
          variant="ghost"
          onClick={() => {
            setLook(DEFAULT_APPEARANCE);
            setColorText(DEFAULT_APPEARANCE.primary_color);
          }}
        >
          기본값으로
        </Button>
        <Button
          disabled={!colorOk || save.isPending}
          onClick={() =>
            save.mutate(
              {
                deploymentId,
                appearance: {
                  ...look,
                  width: clamp(look.width, 300, 640),
                  height: clamp(look.height, 400, 900),
                },
              },
              {
                onSuccess: () =>
                  toast.success(
                    widget
                      ? "저장했어요. 웹사이트를 새로고침하면 5분 안에 바뀌어요."
                      : "저장했어요.",
                  ),
              },
            )
          }
        >
          {save.isPending ? "저장하는 중…" : "모양 저장"}
        </Button>
      </div>
    </div>
  );
}
