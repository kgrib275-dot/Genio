import { Eye } from "lucide-react";
import { ko } from "@/i18n/ko";
import { useViewAs } from "@/store/viewAs";
import { useChangeViewAs } from "./useViewAs";

/** 권한 미리보기 중에만 보이는 위쪽 안내 줄. 누르면 내 권한으로 돌아간다. */
export function ViewAsBanner() {
  const target = useViewAs((s) => s.target);
  const change = useChangeViewAs();
  if (!target) return null;
  return (
    <div
      role="status"
      data-testid="viewas-banner"
      className="flex flex-wrap items-center gap-2 border-b border-sky-300 bg-sky-100 px-4 py-2 text-sm text-sky-900"
    >
      <Eye className="h-4 w-4 shrink-0" />
      <p className="min-w-0 flex-1">
        <b>{ko.roles[target.role]}</b> 권한으로 미리 보는 중이에요. 화면과 서버가 모두 그 권한으로
        동작해요. 여기서 한 일은 실제로 저장되고 활동 기록에 &apos;미리보기&apos;로 남아요.
      </p>
      <button
        type="button"
        onClick={() => change(null)}
        className="rounded-lg border border-sky-400 bg-white px-3 py-1 text-[13px] font-medium hover:bg-sky-50"
      >
        내 권한으로 돌아가기
      </button>
    </div>
  );
}
