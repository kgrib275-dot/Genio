import type { CitationImage, ImageReport } from "@/lib/api/kbcanvas";

/** 서명 주소가 있으면 그대로, 없으면 지식베이스 그림 주소(로그인 필요). 둘 다 없으면 null */
export function imageSource(
  image: CitationImage,
): { kind: "direct" | "authed"; path: string } | null {
  if (image.url) return { kind: "direct", path: image.url };
  if (image.kb_id && image.file_id)
    return { kind: "authed", path: `/knowledge-bases/${image.kb_id}/images/${image.file_id}` };
  return null;
}

export function pageText(page: number | null | undefined): string {
  return page ? `${page}쪽` : "";
}

export type ReportTone = "green" | "amber" | "red" | "gray";

/** 문서별 그림 보고를 한 줄 글로: 설명한 수/그림 수, 실패·건너뜀 */
export function imageReportText(r: ImageReport): {
  text: string;
  tone: ReportTone;
  title: string;
} {
  if (r.skipped) return { text: "그림 설명 건너뜀", tone: "amber", title: r.skipped };
  const images = r.images ?? 0;
  if (images === 0)
    return { text: "그림 없음", tone: "gray", title: "설명할 그림을 찾지 못했어요." };
  const described = r.described ?? 0;
  const failed = r.failed ?? 0;
  const parts = [`AI ${r.calls ?? 0}번 호출`];
  if (failed) parts.push(`${failed}장 실패`);
  if (r.truncated) parts.push(`${r.truncated}장은 한도(20장)를 넘어 뺐어요`);
  return {
    text: `그림 ${described}/${images}장 설명`,
    tone: failed ? "red" : "green",
    title: parts.join(" · "),
  };
}
