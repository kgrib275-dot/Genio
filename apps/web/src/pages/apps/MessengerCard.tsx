import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, MessageCircle } from "lucide-react";
import { useState } from "react";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { api } from "@/lib/api/client";

type Provider = "slack" | "teams";

interface MessengerStatus {
  deployed: boolean;
  slack_url: string;
  teams_url: string;
  slack: { configured: boolean; hint: string };
  teams: { configured: boolean; hint: string };
}

function useMessenger(appId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["messenger", appId],
    queryFn: () => api.get<MessengerStatus>(`/apps/${appId}/messenger`),
    enabled,
    retry: false,
  });
}

function CopyLine({ label, value }: { label: string; value: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="flex items-center gap-2">
      <span className="w-24 shrink-0 text-xs text-slate-500">{label}</span>
      <code className="min-w-0 flex-1 truncate rounded bg-slate-100 px-2 py-1 text-xs">
        {value}
      </code>
      <Button
        size="sm"
        variant="outline"
        aria-label={`${label} 복사`}
        onClick={() => {
          void navigator.clipboard?.writeText(value);
          setDone(true);
          window.setTimeout(() => setDone(false), 1500);
        }}
      >
        {done ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </Button>
    </div>
  );
}

function ProviderBox({
  appId,
  provider,
  title,
  url,
  state,
  steps,
  secretLabel,
  editable,
}: {
  appId: string;
  provider: Provider;
  title: string;
  url: string;
  state: { configured: boolean; hint: string };
  steps: string[];
  secretLabel: string;
  editable: boolean;
}) {
  const qc = useQueryClient();
  const [secret, setSecret] = useState("");
  const save = useMutation({
    mutationFn: () => api.put<MessengerStatus>(`/apps/${appId}/messenger/${provider}`, { secret }),
    onSuccess: (d) => {
      qc.setQueryData(["messenger", appId], d);
      setSecret("");
      toast.success(`${title} 연결을 저장했어요.`);
    },
    onError: (e) => toast.error(e),
  });
  const clear = useMutation({
    mutationFn: () => api.del(`/apps/${appId}/messenger/${provider}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["messenger", appId] });
      toast.success(`${title} 연결을 끊었어요.`);
    },
    onError: (e) => toast.error(e),
  });
  return (
    <div className="space-y-2 rounded-xl border border-slate-200 p-3">
      <div className="flex items-center gap-2">
        <p className="text-sm font-semibold">{title}</p>
        <span
          className={
            state.configured
              ? "rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800"
              : "rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600"
          }
        >
          {state.configured ? "연결됨" : "연결 안 됨"}
        </span>
      </div>
      <ol className="list-decimal space-y-0.5 pl-5 text-xs text-slate-600">
        {steps.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ol>
      <CopyLine label="붙여 넣을 주소" value={url} />
      {editable && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-0 flex-1">
            <Field label={secretLabel} htmlFor={`msg-${provider}`}>
              <Input
                id={`msg-${provider}`}
                type="password"
                autoComplete="off"
                placeholder={state.configured ? `저장됨(${state.hint}) · 바꾸려면 새로 입력` : ""}
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
              />
            </Field>
          </div>
          <Button disabled={!secret.trim() || save.isPending} onClick={() => save.mutate()}>
            저장
          </Button>
          {state.configured && (
            <Button variant="outline" disabled={clear.isPending} onClick={() => clear.mutate()}>
              연결 끊기
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/** 배포·설정: 슬랙·팀즈 안에서 이 앱에 바로 물어보게 하는 연결 */
export function MessengerCard({ appId, editable }: { appId: string; editable: boolean }) {
  const q = useMessenger(appId, editable);
  if (!editable) return null;
  const needDeploy = q.data?.deployed === false;
  return (
    <Card>
      <CardHeader
        title="슬랙·팀즈에서 쓰기"
        description="사람들이 메신저를 떠나지 않고 이 앱에 바로 물어볼 수 있어요. 공유 링크로 배포해야 해요."
      />
      <CardBody className="space-y-3">
        {q.isLoading && <Loading />}
        {needDeploy && (
          <p className="flex items-center gap-2 text-sm text-slate-600">
            <MessageCircle className="h-4 w-4" /> 먼저 위에서 &apos;공유 링크&apos;로 배포해 주세요.
          </p>
        )}
        <ErrorBox error={q.error} />
        {q.data?.deployed && (
          <>
            <ProviderBox
              appId={appId}
              provider="slack"
              title="슬랙"
              url={q.data.slack_url}
              state={q.data.slack}
              secretLabel="Signing Secret(슬랙 앱 > Basic Information)"
              steps={[
                "슬랙 앱을 만들고 Slash Commands에서 /제니오 명령을 추가해요.",
                "Request URL에 아래 주소를 붙여 넣어요.",
                "Signing Secret을 복사해 아래에 저장해요.",
                "슬랙에서 /제니오 연차는 며칠이에요? 처럼 물어보세요.",
              ]}
              editable={editable}
            />
            <ProviderBox
              appId={appId}
              provider="teams"
              title="팀즈"
              url={q.data.teams_url}
              state={q.data.teams}
              secretLabel="보안 토큰(나가는 웹훅을 만들 때 받는 값)"
              steps={[
                "팀즈 채널 > 앱 관리 > 나가는 웹훅 만들기를 눌러요.",
                "콜백 URL에 아래 주소를 붙여 넣어요.",
                "만들면 나오는 보안 토큰을 복사해 아래에 저장해요.",
                "팀즈에서 @이름 연차는 며칠이에요? 처럼 물어보세요.",
              ]}
              editable={editable}
            />
            <p className="text-xs text-slate-500">
              연결하면 그 슬랙·팀즈를 쓰는 누구나 이 앱에 물어볼 수 있어서, 공유 범위가 "누구나"인
              앱만 연결할 수 있어요. 중요한 문서가 있다면 공개해도 되는 앱인지 먼저 확인하세요. 답은
              슬랙·팀즈를 쓰는 사람마다 따로 이어져요.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  );
}
