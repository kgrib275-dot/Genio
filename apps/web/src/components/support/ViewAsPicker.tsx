import { ko } from "@/i18n/ko";
import type { Role } from "@/lib/api/types";
import { useViewAs } from "@/store/viewAs";
import { useChangeViewAs } from "./useViewAs";

/** 미리 볼 수 있는 역할(위에서 아래로 권한이 낮아진다) */
const PREVIEW_ROLES: Role[] = ["admin", "builder", "operator", "member"];

/** 사이드바의 '권한 미리보기' 선택(서비스 관리자만 보인다). */
export function ViewAsPicker() {
  const target = useViewAs((s) => s.target);
  const change = useChangeViewAs();
  return (
    <div className="px-3 pb-3">
      <label htmlFor="view-as" className="mb-1 block px-1 text-[11px] font-medium text-slate-400">
        권한 미리보기
      </label>
      <select
        id="view-as"
        aria-label="권한 미리보기"
        title="다른 역할이 보는 화면과 권한을 그대로 확인해요"
        className="w-full truncate rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
        value={target?.role ?? ""}
        onChange={(e) => change((e.target.value || null) as Role | null)}
      >
        <option value="">내 권한 그대로</option>
        {PREVIEW_ROLES.map((r) => (
          <option key={r} value={r}>
            {ko.roles[r]}로 보기
          </option>
        ))}
      </select>
    </div>
  );
}
