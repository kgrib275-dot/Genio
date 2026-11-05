// 배포 모양(위젯 색·위치·버튼 글·인사 말풍선·창 크기)을 바꾸고 바로 미리 본다.
import { ImagePlus, MessageCircle, Trash2, X } from "lucide-react";
import { useRef, useState, type CSSProperties } from "react";
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
import { uploadWorkspaceFile } from "@/lib/api/v2";
import { cn } from "@/lib/cn";
import { useSession } from "@/store/session";

const THUMB_MAX_BYTES = 2 * 1024 * 1024;
const THUMB_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];

/** 링크를 붙였을 때 메신저에 뜨는 모습(카드) 미리 보기 */
function SharePreviewCard({
  title,
  description,
  imageUrl,
}: {
  title: string;
  description: string;
  imageUrl: string;
}) {
  return (
    <div
      aria-label="공유 미리보기"
      className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
    >
      <img src={imageUrl} alt="" className="aspect-[1200/630] w-full bg-slate-100 object-cover" />
      <div className="space-y-0.5 px-3 py-2">
        <p className="text-[10px] text-slate-400">제니오</p>
        <p className="line-clamp-2 text-[13px] font-semibold leading-snug text-slate-900">
          {title}
        </p>
        <p className="line-clamp-2 text-[11px] leading-snug text-slate-500">{description}</p>
      </div>
    </div>
  );
}

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
  appDescription,
  shareToken,
  onClose,
}: {
  appId: string;
  deploymentId: string;
  initial: Partial<Appearance> | undefined;
  widget: boolean;
  appName: string;
  /** 앱 소개(공유 소개 문구를 비웠을 때 쓰는 글) */
  appDescription?: string;
  /** 이미 저장한 썸네일을 미리 볼 때 쓰는 공유 토큰 */
  shareToken?: string;
  onClose: () => void;
}) {
  const ws = useSession((s) => s.workspaceId);
  const fileRef = useRef<HTMLInputElement>(null);
  const [localThumb, setLocalThumb] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [look, setLook] = useState<Appearance>(() => appearanceOf(initial));
  const [colorText, setColorText] = useState(look.primary_color);
  const save = useUpdateAppearance(appId);
  const set = <K extends keyof Appearance>(k: K, v: Appearance[K]) =>
    setLook((l) => ({ ...l, [k]: v }));
  const colorOk = HEX_COLOR.test(colorText);
  const thumbUrl =
    localThumb ??
    (look.share_image && shareToken
      ? `/api/v1/public/apps/${shareToken}/share-image?v=${look.share_image}`
      : "/og-image.png");

  async function pickThumb(file: File | undefined) {
    if (!file) return;
    if (!THUMB_TYPES.includes(file.type)) {
      toast.error("PNG·JPG·WEBP·GIF 그림만 쓸 수 있어요. 다른 그림 파일을 골라 주세요.");
      return;
    }
    if (file.size > THUMB_MAX_BYTES) {
      toast.error("그림이 너무 커요(최대 2MB). 크기를 줄여서 다시 올려 주세요.");
      return;
    }
    setUploading(true);
    try {
      const saved = await uploadWorkspaceFile(ws, file);
      set("share_image", saved.id);
      setLocalThumb(URL.createObjectURL(file));
    } catch (err) {
      toast.error(err);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }
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
          {!widget && (
            <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-3">
              <p className="text-sm font-semibold text-slate-800">공유 미리보기</p>
              <p className="-mt-2 text-xs text-slate-500">
                링크를 카카오톡·슬랙·메일에 붙였을 때 보이는 제목·소개 문구·썸네일이에요. 누구나 열
                수 있는 앱만 이 내용이 보이고, 멤버 전용 앱은 일반 소개만 나가요.
              </p>
              <Field label="공유 제목(비우면 앱 이름)" htmlFor={`stitle-${deploymentId}`}>
                <Input
                  id={`stitle-${deploymentId}`}
                  maxLength={60}
                  value={look.share_title}
                  placeholder={appName}
                  onChange={(e) => set("share_title", e.target.value)}
                />
              </Field>
              <Field
                label="소개 문구(비우면 앱 설명)"
                htmlFor={`sdesc-${deploymentId}`}
                hint={`${look.share_description.length}/160자`}
              >
                <Textarea
                  id={`sdesc-${deploymentId}`}
                  maxLength={160}
                  rows={2}
                  value={look.share_description}
                  placeholder={appDescription || "예: 연차·반차를 말로 신청하세요."}
                  onChange={(e) => set("share_description", e.target.value)}
                />
              </Field>
              <Field
                label="썸네일 그림"
                htmlFor={`sthumb-${deploymentId}`}
                hint="1200×630 크기를 권장해요. PNG·JPG·WEBP·GIF, 2MB 이하. 비우면 제니오 기본 그림이 나가요."
              >
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    ref={fileRef}
                    id={`sthumb-${deploymentId}`}
                    type="file"
                    accept={THUMB_TYPES.join(",")}
                    className="sr-only"
                    onChange={(e) => void pickThumb(e.target.files?.[0])}
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={uploading}
                    onClick={() => fileRef.current?.click()}
                  >
                    <ImagePlus className="h-3.5 w-3.5" />{" "}
                    {uploading ? "올리는 중…" : look.share_image ? "그림 바꾸기" : "그림 올리기"}
                  </Button>
                  {look.share_image && (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="text-red-600"
                      onClick={() => {
                        set("share_image", "");
                        setLocalThumb(null);
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" /> 기본 그림으로
                    </Button>
                  )}
                </div>
              </Field>
              <SharePreviewCard
                title={look.share_title || appName}
                description={
                  look.share_description ||
                  appDescription ||
                  "말로 요청하면 일하는 앱이 만들어져요. 챗봇·자동화·사람 승인까지 코딩 없이 한 곳에서."
                }
                imageUrl={thumbUrl}
              />
            </div>
          )}
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
