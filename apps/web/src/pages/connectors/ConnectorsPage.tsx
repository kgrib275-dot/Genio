import { HelpButton } from "@/help/HelpButton";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Empty, PageHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { ko } from "@/i18n/ko";
import {
  useConnectorDefinitions,
  useCreateCredential,
  useCredentials,
  useDeleteCredential,
} from "@/lib/api/resources";
import { formatDate } from "@/lib/cn";
import { optionsFrom, useListControls } from "@/lib/useListControls";
import { canEdit, canManage, useSession } from "@/store/session";

function NewCredentialForm({ ws }: { ws: string }) {
  const defs = useConnectorDefinitions(ws);
  const create = useCreateCredential(ws);
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const def = (defs.data ?? []).find((d) => d.key === key);
  const fields = def?.manifest.requires?.credentials ?? [];

  if (defs.data && defs.data.length === 0) {
    return (
      <Empty>
        설치된 서비스가 없어요.{" "}
        <Link className="text-indigo-600" to="/market?type=connector">
          마켓
        </Link>
        에서 슬랙·메일 같은 서비스를 먼저 설치하세요.
      </Empty>
    );
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate(
      { connector_key: key, name, secrets },
      {
        onSuccess: () => {
          toast.success("연결 정보를 저장했어요. 값은 암호화되어 다시 볼 수 없어요.");
          setName("");
          setSecrets({});
        },
      },
    );
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="서비스" htmlFor="cred-def">
        <Select
          id="cred-def"
          required
          value={key}
          onChange={(e) => {
            setKey(e.target.value);
            setSecrets({});
          }}
        >
          <option value="">서비스 선택</option>
          {(defs.data ?? []).map((d) => (
            <option key={d.id} value={d.key}>
              {d.name}
            </option>
          ))}
        </Select>
      </Field>
      <Field
        label="이름"
        htmlFor="cred-name"
        hint="흐름에서 고를 때 보이는 이름이에요. 예: 고객지원 슬랙"
      >
        <Input id="cred-name" required value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      {fields.map((f) => (
        <Field key={f.key} label={f.label} htmlFor={`sec-${f.key}`}>
          <Input
            id={`sec-${f.key}`}
            type={f.secret ? "password" : "text"}
            autoComplete="off"
            required
            value={secrets[f.key] ?? ""}
            onChange={(e) => setSecrets({ ...secrets, [f.key]: e.target.value })}
          />
        </Field>
      ))}
      <ErrorBox error={create.error} />
      <Button type="submit" disabled={create.isPending || !key || !name}>
        저장
      </Button>
    </form>
  );
}

export default function ConnectorsPage() {
  const { workspaceId: ws, role } = useSession();
  const creds = useCredentials(ws, canEdit(role));
  const del = useDeleteCredential(ws);
  const manage = canManage(role);
  const cc = useListControls(creds.data, {
    key: "credentials",
    search: (c) => `${c.name} ${c.connector_name}`,
    filters: [
      {
        id: "connector",
        label: "서비스",
        options: optionsFrom(creds.data, (c) => c.connector_name),
        match: (c, v) => c.connector_name === v,
      },
    ],
  });

  if (!canEdit(role)) {
    return (
      <PageContainer>
        <PageHeader title="연결 정보" />
        <Empty>{ko.common.noPermission}</Empty>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title="연결 정보"
        description="슬랙 토큰 같은 비밀값을 안전하게 보관해요. 흐름은 이름으로만 고르고 값은 볼 수 없어요."
        help={<HelpButton page="connectors" />}
      />
      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <Card>
          <CardHeader title="등록된 연결 정보" />
          <CardBody className="p-0">
            {creds.isLoading && <Loading />}
            <ErrorBox error={creds.error} />
            {creds.data?.length === 0 && (
              <p className="px-5 py-6 text-sm text-slate-500">아직 등록된 연결 정보가 없어요.</p>
            )}
            {(creds.data ?? []).length > 0 && (
              <ListToolbar
                c={cc}
                placeholder="이름·서비스로 찾기"
                className="border-b border-slate-100 px-5 pb-3"
              />
            )}
            <NoMatch c={cc} />
            <ul className="divide-y divide-slate-100">
              {cc.pageItems.map((c) => (
                <li key={c.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
                  <Badge tone="blue">{c.connector_name}</Badge>
                  <span className="font-medium">{c.name}</span>
                  <span className="text-xs text-slate-500">
                    {Object.entries(c.secrets_masked)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(" · ")}
                  </span>
                  <span className="ml-auto text-xs text-slate-400">{formatDate(c.created_at)}</span>
                  {manage && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-red-600"
                      onClick={() => {
                        if (
                          window.confirm(
                            `'${c.name}'을(를) 지울까요? 이 연결 정보를 쓰는 흐름은 실패하게 돼요.`,
                          )
                        ) {
                          del.mutate(c.id, { onError: (err) => toast.error(err) });
                        }
                      }}
                    >
                      삭제
                    </Button>
                  )}
                </li>
              ))}
            </ul>
            {(creds.data ?? []).length > 0 && (
              <ListPager c={cc} className="border-t border-slate-100 px-5 py-2.5" />
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="새 연결 정보" />
          <CardBody>
            {manage ? (
              <NewCredentialForm ws={ws} />
            ) : (
              <p className="text-sm text-slate-500">{ko.common.noPermission}</p>
            )}
          </CardBody>
        </Card>
      </div>
    </PageContainer>
  );
}
