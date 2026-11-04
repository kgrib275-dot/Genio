// v0.7 관리 > 시스템 설정 > 시스템 메일(비밀번호 찾기·이메일 인증 메일을 보내는 메일 서버)
import { Mail, Send } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import {
  useMailSettings,
  useSaveMailSettings,
  useTestMail,
  type MailSettings,
} from "@/lib/api/account";

export function SystemMailCard({ canEdit }: { canEdit: boolean }) {
  const mail = useMailSettings(canEdit);
  const save = useSaveMailSettings();
  const test = useTestMail();
  const [form, setForm] = useState<Partial<MailSettings> & { password?: string }>({});
  useEffect(() => {
    if (mail.data) setForm({ ...mail.data, password: "" });
  }, [mail.data]);
  if (!canEdit) return null;
  const set = (k: keyof MailSettings | "password", v: string | number) =>
    setForm((f) => ({ ...f, [k]: v }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const { password, ...rest } = form;
    save.mutate(
      { ...rest, ...(password ? { password } : {}) },
      { onSuccess: () => toast.success("메일 설정을 저장했어요. 시험 메일을 보내 확인해 보세요.") },
    );
  };
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Mail className="h-4 w-4 text-indigo-500" /> 시스템 메일
            {mail.data?.configured ? <Badge tone="green">설정됨</Badge> : <Badge>설정 안 됨</Badge>}
          </span>
        }
        description="비밀번호 찾기·이메일 확인 메일을 보낼 메일 서버예요. 회사 메일(SMTP)이나 메일 발송 서비스 정보를 넣어요."
      />
      <CardBody>
        {mail.isLoading && <Loading />}
        <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
          <Field label="메일 서버 주소" htmlFor="smtp-host">
            <Input
              id="smtp-host"
              placeholder="smtp.gmail.com"
              value={form.host ?? ""}
              onChange={(e) => set("host", e.target.value)}
            />
          </Field>
          <Field label="포트" htmlFor="smtp-port" hint="보통 587(STARTTLS) 또는 465(SSL)">
            <Input
              id="smtp-port"
              type="number"
              value={form.port ?? 587}
              onChange={(e) => set("port", Number(e.target.value))}
            />
          </Field>
          <Field label="보안 방식" htmlFor="smtp-sec">
            <Select
              id="smtp-sec"
              value={form.security ?? "starttls"}
              onChange={(e) => set("security", e.target.value)}
            >
              <option value="starttls">STARTTLS(587)</option>
              <option value="ssl">SSL(465)</option>
              <option value="none">없음(사내 중계 서버)</option>
            </Select>
          </Field>
          <Field label="로그인 아이디" htmlFor="smtp-user">
            <Input
              id="smtp-user"
              autoComplete="off"
              value={form.username ?? ""}
              onChange={(e) => set("username", e.target.value)}
            />
          </Field>
          <Field
            label="비밀번호"
            htmlFor="smtp-pw"
            hint={
              mail.data?.password_masked
                ? `저장됨 ${mail.data.password_masked} · 바꿀 때만 적어요`
                : "앱 비밀번호를 쓰는 메일도 있어요(예: Gmail)"
            }
          >
            <Input
              id="smtp-pw"
              type="password"
              autoComplete="new-password"
              value={form.password ?? ""}
              onChange={(e) => set("password", e.target.value)}
            />
          </Field>
          <Field label="보내는 주소" htmlFor="smtp-from">
            <Input
              id="smtp-from"
              type="email"
              placeholder="noreply@company.com"
              value={form.from_addr ?? ""}
              onChange={(e) => set("from_addr", e.target.value)}
            />
          </Field>
          <Field label="보내는 이름" htmlFor="smtp-name">
            <Input
              id="smtp-name"
              value={form.from_name ?? "Genio"}
              onChange={(e) => set("from_name", e.target.value)}
            />
          </Field>
          <div className="flex flex-wrap items-end gap-2 sm:col-span-2">
            <Button type="submit" disabled={save.isPending}>
              저장
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={test.isPending || !mail.data?.configured}
              onClick={() => test.mutate(undefined, { onSuccess: (r) => toast.success(r.message) })}
            >
              <Send className="h-4 w-4" /> 시험 메일 보내기(나에게)
            </Button>
          </div>
          <div className="sm:col-span-2">
            <ErrorBox error={save.error ?? test.error ?? mail.error} />
          </div>
        </form>
      </CardBody>
    </Card>
  );
}
