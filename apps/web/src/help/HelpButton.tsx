import { HelpCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Dialog } from "@/components/ui/dialog";
import { PAGE_HELP, helpSection, type HelpPageKey } from "@/help/content";
import { HelpSectionView } from "@/help/HelpView";
import { cn } from "@/lib/cn";

/** 화면 머리글에 두는 작은 '?' 버튼. 누르면 이 화면 설명을 팝업으로 보여 준다. */
export function HelpButton({
  page,
  fullLink = true,
  className,
}: {
  page: HelpPageKey;
  fullLink?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const section = helpSection(PAGE_HELP[page]);
  return (
    <>
      <button
        type="button"
        aria-label="이 화면 사용 설명"
        title="이 화면 사용 설명"
        onClick={() => setOpen(true)}
        className={cn(
          "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-100 hover:text-indigo-600",
          className,
        )}
      >
        <HelpCircle className="h-[18px] w-[18px]" />
      </button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={`도움말 · ${section.title}`}
        wide
        footer={
          fullLink ? (
            <Link
              to={`/help#${section.id}`}
              onClick={() => setOpen(false)}
              className="text-sm font-medium text-indigo-600 hover:underline"
            >
              전체 설명서 보기
            </Link>
          ) : undefined
        }
      >
        <HelpSectionView section={section} heading={false} />
      </Dialog>
    </>
  );
}
