// v0.6 화면이 예기치 않게 깨졌을 때 보여 줄 친절한 화면(두 줄: 무엇이 문제 + 어떻게 하면 되는지).
// 화면 안(메뉴 옆)에서 깨지면 메뉴는 그대로 두고 본문만 이 화면으로 바꾼다.
import { AlertTriangle, MessageCircleQuestion, RotateCcw } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { openHelp } from "@/lib/helpEvents";

export function ErrorScreen({
  title,
  hint,
  onRetry,
  detail,
}: {
  title: string;
  hint: string;
  onRetry?: () => void;
  detail?: string;
}) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4 py-12">
      <div className="max-w-md text-center">
        <span className="mx-auto mb-4 inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-amber-50 text-amber-600">
          <AlertTriangle className="h-6 w-6" />
        </span>
        <h1 className="text-lg font-bold text-slate-900">{title}</h1>
        <p className="mt-1 text-sm text-slate-600">{hint}</p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          {onRetry && (
            <Button onClick={onRetry}>
              <RotateCcw className="h-4 w-4" /> 다시 시도
            </Button>
          )}
          <Button
            variant="outline"
            onClick={() => {
              if (!openHelp("feedback", detail ? `화면 오류: ${detail}` : "")) {
                window.location.assign("/help#faq");
              }
            }}
          >
            <MessageCircleQuestion className="h-4 w-4" /> 문의하기
          </Button>
          <Link
            to="/"
            className="inline-flex items-center rounded-lg px-3 py-2 text-sm text-slate-500 hover:bg-slate-100"
          >
            처음 화면으로
          </Link>
        </div>
      </div>
    </div>
  );
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 개발 중 원인 확인용(사용자 화면에는 영어 원문을 보이지 않는다)
    console.error("화면 오류", error, info.componentStack);
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    // 다른 화면으로 옮기면 오류 화면을 거둔다
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    if (this.state.error) {
      const chunk = /dynamically imported module|Loading chunk|Failed to fetch/i.test(
        this.state.error.message,
      );
      return (
        <ErrorScreen
          title={
            chunk ? "새 버전이 나와 화면을 다시 불러와야 해요." : "이 화면을 보여 주지 못했어요."
          }
          hint={
            chunk
              ? "'다시 시도'를 누르면 새로 고쳐져요."
              : "'다시 시도'를 누르고, 계속되면 '문의하기'로 알려 주세요."
          }
          detail={this.state.error.message.slice(0, 200)}
          onRetry={() => {
            if (chunk) window.location.reload();
            else this.setState({ error: null });
          }}
        />
      );
    }
    return this.props.children;
  }
}
