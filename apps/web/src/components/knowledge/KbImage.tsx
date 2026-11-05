// 검색 결과·인용에 붙는 문서 속 그림 썸네일(v0.9 이미지 색인).
// 공개 챗: 서버가 붙인 24시간 서명 주소(url)를 그대로 쓴다. 빌더: 로그인 정보로 그림을 받아 보여 준다.
import { ImageOff } from "lucide-react";
import { useEffect, useState } from "react";
import { rawRequest } from "@/lib/api/client";
import type { CitationImage } from "@/lib/api/kbcanvas";
import { imageSource } from "@/lib/kbImageSource";
import { cn } from "@/lib/cn";

export function KbImage({ image, className }: { image: CitationImage; className?: string }) {
  const source = imageSource(image);
  const [src, setSrc] = useState<string | null>(source?.kind === "direct" ? source.path : null);
  const [failed, setFailed] = useState(false);
  const kind = source?.kind;
  const path = source?.path;

  useEffect(() => {
    if (kind !== "authed" || !path) return;
    let url: string | null = null;
    let alive = true;
    rawRequest(path)
      .then(async (res) => {
        if (!res.ok) throw new Error("load");
        const blob = await res.blob();
        if (!alive) return;
        url = URL.createObjectURL(blob);
        setSrc(url);
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [kind, path]);

  const label = image.caption || "문서 속 그림";
  if (!source || failed)
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-[11px] text-slate-500",
          className,
        )}
      >
        <ImageOff className="h-3 w-3" /> 그림을 불러오지 못했어요
      </span>
    );
  if (!src)
    return (
      <span
        className={cn("block h-20 w-28 animate-pulse rounded-lg bg-slate-100", className)}
        aria-label="그림을 불러오는 중"
      />
    );
  return (
    <a href={src} target="_blank" rel="noreferrer" title={`${label} (눌러서 크게 보기)`}>
      <img
        src={src}
        alt={label}
        loading="lazy"
        onError={() => setFailed(true)}
        className={cn(
          "max-h-28 max-w-[10rem] rounded-lg border border-slate-200 bg-white object-contain",
          className,
        )}
      />
    </a>
  );
}
