// sections.tsx에서 분리한 구간: SystemSection
import { useEffect, useState } from "react";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { useAnnouncement, useSaveAnnouncement } from "@/lib/api/announcement";
import {
  useSystemSettings,
  useUpdateSystemSettings,
  useUpdateWorkspace,
  useWorkspaceInfo,
} from "@/lib/api/v2";
import { SystemMailCard } from "@/pages/workspace/SystemMailCard";

// ---------------- 시스템 설정 ----------------
function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${checked ? "bg-indigo-600" : "bg-slate-300"}`}
    >
      <span
        className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-5" : "translate-x-0.5"}`}
      />
    </button>
  );
}

export function SystemSection({ ws }: { ws: string }) {
  const sys = useSystemSettings();
  const updateSys = useUpdateSystemSettings();
  const info = useWorkspaceInfo(ws);
  const updateWs = useUpdateWorkspace(ws);
  const [name, setName] = useState("");
  const [rate, setRate] = useState(30);
  useEffect(() => {
    if (info.data) {
      setName(info.data.name);
      setRate(info.data.settings?.public_rate_limit_per_minute ?? 30);
    }
  }, [info.data]);
  const canSys = Boolean(sys.data?.is_instance_admin);

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {canSys && <AnnouncementCard />}
      <Card>
        <CardHeader title="워크스페이스" description="이름과 공개 챗 속도 제한을 정해요." />
        <CardBody className="space-y-3">
          {info.isLoading && <Loading />}
          <ErrorBox error={info.error ?? updateWs.error} />
          <Field label="이름" htmlFor="ws-name">
            <Input id="ws-name" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field
            label="공개 챗 속도 제한(분당, IP마다)"
            htmlFor="ws-rate"
            hint="한 사람이 1분에 보낼 수 있는 질문 수예요."
          >
            <Input
              id="ws-rate"
              type="number"
              min={1}
              max={600}
              value={rate}
              onChange={(e) => setRate(Math.max(1, Math.min(600, Number(e.target.value) || 30)))}
            />
          </Field>
          <Button
            size="sm"
            disabled={updateWs.isPending || !name.trim()}
            onClick={() =>
              updateWs.mutate(
                {
                  name,
                  settings: { ...(info.data?.settings ?? {}), public_rate_limit_per_minute: rate },
                },
                { onSuccess: () => toast.success("저장했어요.") },
              )
            }
          >
            저장
          </Button>
        </CardBody>
      </Card>
      <Card>
        <CardHeader
          title="시스템"
          description={
            canSys
              ? "이 서버 전체에 적용돼요."
              : "가장 먼저 만든 워크스페이스의 소유자만 바꿀 수 있어요."
          }
        />
        <CardBody className="space-y-4">
          {sys.isLoading && <Loading />}
          <ErrorBox error={sys.error ?? updateSys.error} />
          {sys.data && (
            <>
              <div className="flex items-start gap-3">
                <div className="flex-1">
                  <p className="text-sm font-medium">회원가입 허용</p>
                  <p className="text-xs text-slate-500">
                    끄면 초대받은 사람만 계정을 만들 수 있어요. 인터넷에 공개했다면 끄는 게
                    안전해요.
                  </p>
                </div>
                <Switch
                  label="회원가입 허용"
                  checked={sys.data.allow_signup}
                  disabled={!canSys || updateSys.isPending}
                  onChange={(v) => updateSys.mutate({ allow_signup: v })}
                />
              </div>
              <div className="flex items-start gap-3">
                <div className="flex-1">
                  <p className="text-sm font-medium">가입 시 이메일 확인 필수</p>
                  <p className="text-xs text-slate-500">
                    켜면 새로 가입한 사람은 메일의 링크를 열어야 로그인할 수 있어요. 아래 시스템
                    메일을 먼저 설정해야 해요. 이미 있는 계정은 그대로 로그인돼요.
                  </p>
                </div>
                <Switch
                  label="가입 시 이메일 확인 필수"
                  checked={Boolean(sys.data.require_email_verification)}
                  disabled={!canSys || updateSys.isPending}
                  onChange={(v) => updateSys.mutate({ require_email_verification: v })}
                />
              </div>
            </>
          )}
        </CardBody>
      </Card>
      <SystemMailCard canEdit={canSys} />
    </div>
  );
}

/** 서비스 전체 공지 올리기(서비스 관리자만). 비우고 저장하면 내려가요. */
function AnnouncementCard() {
  const q = useAnnouncement();
  const save = useSaveAnnouncement();
  const [message, setMessage] = useState("");
  const [level, setLevel] = useState<"info" | "warn" | "maintenance">("info");
  const [until, setUntil] = useState("");
  useEffect(() => {
    if (q.data?.active) {
      setMessage(q.data.message);
      setLevel(q.data.level);
      setUntil(q.data.until ? q.data.until.slice(0, 16) : "");
    }
  }, [q.data]);
  return (
    <Card className="lg:col-span-2">
      <CardHeader
        title="서비스 공지"
        description="모든 사용자 화면 위쪽과 상태 페이지(/status)에 보여요. 점검·장애를 알릴 때 써요."
      />
      <CardBody className="space-y-3">
        <ErrorBox error={save.error} />
        <Field label="공지 내용(비우고 저장하면 내려가요)" htmlFor="ann-msg">
          <Input
            id="ann-msg"
            maxLength={300}
            placeholder="예: 오늘 밤 2시~3시에 점검이 있어요. 이 시간에는 쓸 수 없어요."
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="종류" htmlFor="ann-level">
            <Select
              id="ann-level"
              value={level}
              onChange={(e) => setLevel(e.target.value as typeof level)}
            >
              <option value="info">안내</option>
              <option value="warn">주의</option>
              <option value="maintenance">점검·장애</option>
            </Select>
          </Field>
          <Field
            label="이 시각까지 보여요(선택)"
            htmlFor="ann-until"
            hint="비우면 내릴 때까지 보여요."
          >
            <Input
              id="ann-until"
              type="datetime-local"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
            />
          </Field>
        </div>
        <Button
          disabled={save.isPending}
          onClick={() =>
            save.mutate(
              { message, level, until: until ? new Date(until).toISOString() : null },
              {
                onSuccess: () =>
                  toast.success(message.trim() ? "공지를 올렸어요." : "공지를 내렸어요."),
              },
            )
          }
        >
          {save.isPending ? "저장 중…" : "저장"}
        </Button>
      </CardBody>
    </Card>
  );
}
