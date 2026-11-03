// 빌더 옆 '대화로 시험하기': 저장하지 않은 작업본 흐름과 바로 대화해 본다(로그에는 남지 않음).
import { FlaskConical, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ChatView } from "@/components/chat/ChatView";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { useApp } from "@/lib/api/apps";
import { inputFieldsOfGraph, previewTransport } from "@/lib/api/chat";
import { normalizeFeatures, type AppDetailV2 } from "@/lib/api/types";

export default function PreviewChatPanel({
  appId,
  onClose,
}: {
  appId: string;
  onClose: () => void;
}) {
  const app = useApp(appId);
  const [resetKey, setResetKey] = useState(0);
  const transport = useMemo(() => previewTransport(appId), [appId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const detail = app.data as AppDetailV2 | undefined;
  return (
    <aside
      aria-label="대화로 시험하기"
      className="fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-slate-200 bg-white shadow-2xl sm:w-[420px]"
    >
      <div className="flex shrink-0 items-center gap-2 bg-amber-50 px-3 py-1.5 text-[11px] text-amber-800">
        <FlaskConical className="h-3.5 w-3.5 shrink-0" />
        <span className="min-w-0 flex-1">
          저장 전 작업본으로 대화해 봐요. 로그·통계에는 남지 않아요.
        </span>
      </div>
      <div className="min-h-0 flex-1">
        {app.isLoading && <Loading />}
        {app.error && (
          <div className="p-4">
            <ErrorBox error={app.error} />
          </div>
        )}
        {detail && (
          <ChatView
            title={detail.name}
            icon={detail.icon}
            features={normalizeFeatures(detail.features)}
            inputFields={inputFieldsOfGraph(detail.draft_graph)}
            transport={transport}
            variant="panel"
            resetKey={resetKey}
            onClose={onClose}
            headerActions={
              <button
                type="button"
                onClick={() => setResetKey((k) => k + 1)}
                className="inline-flex h-8 shrink-0 items-center gap-1 rounded-lg px-2 text-xs font-medium text-slate-600 hover:bg-slate-100"
                title="대화를 지우고 새로 시작"
              >
                <RotateCcw className="h-3.5 w-3.5" /> 새로 시작
              </button>
            }
          />
        )}
      </div>
    </aside>
  );
}
