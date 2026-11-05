// 문서 줄에 붙는 그림 색인 결과: "그림 2/3장 설명" / "그림 설명 건너뜀"
import { Badge } from "@/components/ui/badge";
import type { ImageReport } from "@/lib/api/kbcanvas";
import { imageReportText } from "@/lib/kbImageSource";

export function ImageReportBadge({ report }: { report: ImageReport }) {
  const { text, tone, title } = imageReportText(report);
  return (
    <span title={title}>
      <Badge tone={tone}>{text}</Badge>
    </span>
  );
}
