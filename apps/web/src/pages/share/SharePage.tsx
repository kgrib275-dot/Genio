import { useMemo } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useLoggedIn } from "@/app/useAuthState";
import { AppIcon } from "@/components/AppIcon";
import { ChatView } from "@/components/chat/ChatView";
import { WorkflowFormView } from "@/components/chat/WorkflowFormView";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { HelpButton } from "@/help/HelpButton";
import { ko } from "@/i18n/ko";
import { appearanceOf, askParentToClose, publicTransport, type PublicAppV4 } from "@/lib/api/chat";
import { usePublicApp } from "@/lib/api/resources";

/** 배포된 앱을 쓰는 화면. 위젯(iframe)은 ?embed=1 로 연다. */
export default function SharePage() {
  const { token = "" } = useParams();
  const [params] = useSearchParams();
  const embed = params.get("embed") === "1";
  const loggedIn = useLoggedIn();
  const app = usePublicApp(token);
  const transport = useMemo(() => publicTransport(token), [token]);

  if (app.isLoading) return <Loading />;
  if (app.error)
    return (
      <div className="mx-auto max-w-md p-6">
        <ErrorBox error={app.error} />
      </div>
    );
  const info = app.data as PublicAppV4 | undefined;
  if (!info) return null;
  const look = appearanceOf(info.appearance);
  const title = look.title || info.name;

  if (!info.can_use) {
    const needLogin = info.requires_login && !loggedIn;
    return (
      <div className="flex h-[100dvh] flex-col bg-slate-50">
        <header className="flex shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-3 py-2.5 sm:px-4">
          <AppIcon name={info.name} icon={info.icon} size="sm" />
          <p className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</p>
        </header>
        <div className="mx-auto w-full max-w-md p-6 text-sm">
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
            <p className="font-medium text-amber-900">
              {needLogin ? "로그인이 필요한 앱이에요." : "이 앱을 쓸 권한이 없어요."}
            </p>
            <p className="text-amber-800">
              {needLogin
                ? "워크스페이스 계정으로 로그인한 뒤 다시 열어 주세요."
                : "앱을 배포한 사람에게 사용 권한을 요청하세요."}
            </p>
          </div>
          {needLogin && (
            <Link
              to={`/login?next=${encodeURIComponent(`/share/${token}${embed ? "?embed=1" : ""}`)}`}
              target={embed ? "_blank" : undefined}
              className="mt-3 inline-block text-indigo-600"
            >
              로그인하러 가기
            </Link>
          )}
        </div>
      </div>
    );
  }

  // 워크플로우 앱은 대화가 아니라 입력 폼 → 결과로 쓴다
  if (info.type === "workflow")
    return (
      <div className="h-[100dvh]">
        <WorkflowFormView
          token={token}
          title={title}
          icon={info.icon}
          description={info.description}
          fields={info.input_fields}
          accent={look.primary_color}
          headerActions={<HelpButton page="share" fullLink={false} />}
        />
      </div>
    );

  return (
    <div className="h-[100dvh]">
      <ChatView
        title={title}
        icon={info.icon}
        description={info.description}
        features={info.features ?? {}}
        inputFields={info.input_fields}
        transport={transport}
        historyKey={token}
        embed={embed}
        accent={look.primary_color}
        onClose={embed ? askParentToClose : undefined}
        headerActions={
          <>
            {!embed && (
              <span className="hidden whitespace-nowrap px-1 text-xs text-slate-400 md:inline">
                {ko.appName}로 만들었어요
              </span>
            )}
            <HelpButton page="share" fullLink={false} />
          </>
        }
      />
    </div>
  );
}
