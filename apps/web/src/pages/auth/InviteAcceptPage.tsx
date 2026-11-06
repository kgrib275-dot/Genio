import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { ko } from "@/i18n/ko";
import { useAcceptInvitation, useInvitationInfo, useMe } from "@/lib/api/auth";
import { isLoggedIn } from "@/lib/api/client";
import { useSession } from "@/store/session";
import { AuthShell } from "@/pages/auth/AuthShell";
import { AgreementChecks, LegalLinks } from "@/pages/legal/AgreementChecks";

export default function InviteAcceptPage() {
  const { token = "" } = useParams();
  const info = useInvitationInfo(token);
  const accept = useAcceptInvitation(token);
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [agree, setAgree] = useState({ terms: false, privacy: false });
  // 초대받은 이메일로 이미 로그인해 있으면(2단계 인증까지 마친 상태) 비밀번호 없이 바로 수락한다
  const me = useMe(isLoggedIn());
  const sameUser =
    !!me.data && !!info.data && me.data.email.toLowerCase() === info.data.email.toLowerCase();

  const done = {
    onSuccess: () => {
      useSession.getState().setWorkspace("", null);
      navigate("/", { replace: true });
    },
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    accept.mutate({ name, password, agree_terms: agree.terms, agree_privacy: agree.privacy }, done);
  };

  return (
    <AuthShell title="초대 받기" subtitle="워크스페이스에 함께할 준비가 됐어요.">
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
          ) : sameUser && me.data ? (
            <div className="space-y-4">
              <p className="text-sm text-slate-600">
                지금 <b>{me.data.email}</b> 계정으로 로그인해 있어요. 이 계정으로 바로 함께할 수
                있어요.
              </p>
              <ErrorBox error={accept.error} />
              <Button
                className="w-full"
                disabled={accept.isPending}
                onClick={() => accept.mutate({ name: me.data.name, password: "" }, done)}
              >
                이 계정으로 초대 수락하기
              </Button>
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <Field label="이름" htmlFor="name">
                <Input id="name" required value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
              <Field
                label="비밀번호"
                htmlFor="password"
                hint="이미 계정이 있으면 그 비밀번호를, 없으면 새 비밀번호(8자 이상, 영문과 숫자를 섞어서)를 넣어 주세요."
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
              <AgreementChecks value={agree} onChange={setAgree} />
              <ErrorBox error={accept.error} />
              <Button
                type="submit"
                className="w-full"
                disabled={accept.isPending || !agree.terms || !agree.privacy}
              >
                초대 수락하기
              </Button>
            </form>
          )}
        </>
      )}
      <LegalLinks />
    </AuthShell>
  );
}
