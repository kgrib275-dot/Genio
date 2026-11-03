import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { ko } from "@/i18n/ko";
import { useAcceptInvitation, useInvitationInfo } from "@/lib/api/auth";
import { useSession } from "@/store/session";
import { AuthShell } from "@/pages/auth/AuthShell";

export default function InviteAcceptPage() {
  const { token = "" } = useParams();
  const info = useInvitationInfo(token);
  const accept = useAcceptInvitation(token);
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    accept.mutate(
      { name, password },
      {
        onSuccess: () => {
          useSession.getState().setWorkspace("", null);
          navigate("/", { replace: true });
        },
      },
    );
  };

  return (
    <AuthShell title="초대 받기">
      {info.isLoading && <Loading />}
      <ErrorBox error={info.error} />
      {info.data && (
        <>
          <p className="mb-4 text-sm text-slate-600">
            <b>{info.data.workspace_name}</b>에 <b>{ko.roles[info.data.role]}</b> 역할로
            초대받았어요.
            <br />
            초대 이메일: {info.data.email}
          </p>
          {info.data.expired || info.data.accepted ? (
            <div className="rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-900">
              <p className="font-medium">
                {info.data.accepted ? "이미 수락한 초대예요." : "초대 기간이 지났어요."}
              </p>
              <p>관리자에게 새 초대를 요청하거나, 로그인해서 계속하세요.</p>
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <Field label="이름" htmlFor="name">
                <Input id="name" required value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
              <Field
                label="비밀번호"
                htmlFor="password"
                hint="이미 계정이 있으면 그 비밀번호를, 없으면 새 비밀번호(8자 이상)를 넣어 주세요."
              >
                <Input
                  id="password"
                  type="password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </Field>
              <ErrorBox error={accept.error} />
              <Button type="submit" className="w-full" disabled={accept.isPending}>
                초대 수락하기
              </Button>
            </form>
          )}
        </>
      )}
    </AuthShell>
  );
}
