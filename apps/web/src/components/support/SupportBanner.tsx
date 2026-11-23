import { useQueryClient } from "@tanstack/react-query";
import { LifeBuoy } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useSession } from "@/store/session";
import { useSupport } from "@/store/support";

/** 지원 접속 중에만 보이는 위쪽 안내 줄. 누르면 지원을 끝내고 내 워크스페이스로 돌아간다. */
export function SupportBanner() {
  const target = useSupport((s) => s.target);
  const exit = useSupport((s) => s.exit);
  const setWorkspace = useSession((s) => s.setWorkspace);
  const qc = useQueryClient();
  const navigate = useNavigate();
  if (!target) return null;
  return (
    <div
      role="status"
      data-testid="support-banner"
      className="flex flex-wrap items-center gap-2 border-b border-amber-300 bg-amber-100 px-4 py-2 text-sm text-amber-900"
    >
      <LifeBuoy className="h-4 w-4 shrink-0" />
      <p className="min-w-0 flex-1">
        <b>{target.name}</b> 지원 접속 중 ·{" "}
        {target.level === "edit" ? "수정까지 허용됨" : "보기만 가능"}. 접속과 수정은 이 회사의 활동
        기록에 남아요.
      </p>
      <button
        type="button"
        onClick={() => {
          const prev = exit();
          if (prev) setWorkspace(prev.back.id, prev.back.role);
          qc.clear();
          navigate("/admin?tab=companies");
        }}
        className="rounded-lg border border-amber-400 bg-white px-3 py-1 text-[13px] font-medium hover:bg-amber-50"
      >
        지원 끝내기
      </button>
    </div>
  );
}
