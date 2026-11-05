import { HelpButton } from "@/help/HelpButton";
import { CheckCircle2, KeyRound, Plug, PlugZap, XCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { PageContainer } from "@/app/Layout";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Empty, PageHeader } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { ko } from "@/i18n/ko";
import {
  useConnectorDefinitions,
  useCreateCredential,
  useCredentials,
  useDeleteCredential,
} from "@/lib/api/resources";
import { formatDate } from "@/lib/cn";
import {
  usePrivateHosts,
  useSetPrivateHosts,
  useTestCredential,
  type CredentialTestResult,
} from "@/lib/api/v5b";
import { optionsFrom, useListControls } from "@/lib/useListControls";
import { canEdit, canManage, useSession } from "@/store/session";
import { EmptyState } from "@/components/EmptyState";
import { ApiToolImportCard } from "@/pages/connectors/ApiToolImportCard";
import { McpServerCard, McpToolsButton } from "@/pages/connectors/McpServerCard";

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
      <EmptyState
        icon={<Plug className="h-5 w-5" />}
        title="설치된 서비스가 없어요"
        description="슬랙·메일·노션 같은 서비스를 마켓에서 먼저 설치하면, 여기서 연결 정보(키·토큰)를 등록할 수 있어요."
        action={{ label: "마켓에서 서비스 찾기", to: "/market?type=connector" }}
      />
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
        <Field
          key={f.key}
          label={(f as { required?: boolean }).required === false ? `${f.label} (선택)` : f.label}
          htmlFor={`sec-${f.key}`}
        >
          <Input
            id={`sec-${f.key}`}
            type={f.secret ? "password" : "text"}
            autoComplete="off"
            required={(f as { required?: boolean }).required !== false}
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

function TestResult({ r }: { r: CredentialTestResult }) {
  return (
    <p
      role="status"
      className={`basis-full rounded-md px-3 py-2 text-xs ${
        r.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"
      }`}
    >
      <span className="inline-flex items-center gap-1 font-medium">
        {r.ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
        {r.ok ? (r.checked ? "연결이 잘 돼요" : "확인 기능 없음") : "연결에 실패했어요"}
      </span>
      <span className="ml-1">{r.message}</span>
    </p>
  );
}

/** 사내망(내부 IP)의 DB 등을 쓰려면 관리자가 호스트를 허용한다. */
function PrivateHostsCard({ ws }: { ws: string }) {
  const hosts = usePrivateHosts(ws);
  const save = useSetPrivateHosts(ws);
  const [text, setText] = useState<string | null>(null);
  const value = text ?? (hosts.data?.hosts ?? []).join("\n");
  return (
    <Card>
      <CardHeader
        title="허용할 내부 주소"
        description="사내 DB처럼 내부망에 있는 서버를 연결할 때만 적어요. 여기에 없는 내부 주소는 언제나 막혀 있어요."
      />
      <CardBody className="space-y-3">
        <Field
          label="호스트(한 줄에 하나)"
          htmlFor="private-hosts"
          hint="예: db.internal.example.com, 10.0.0.5"
        >
          <Textarea
            id="private-hosts"
            rows={3}
            value={value}
            onChange={(e) => setText(e.target.value)}
          />
        </Field>
        <ErrorBox error={save.error} />
        <Button
          size="sm"
          disabled={save.isPending}
          onClick={() =>
            save.mutate(
              value
                .split(/[\n,]/)
                .map((h) => h.trim())
                .filter(Boolean),
              {
                onSuccess: () => {
                  setText(null);
                  toast.success("허용할 내부 주소를 저장했어요.");
                },
              },
            )
          }
        >
          저장
        </Button>
      </CardBody>
    </Card>
  );
}

export default function ConnectorsPage() {
  const { workspaceId: ws, role } = useSession();
  const creds = useCredentials(ws, canEdit(role));
  const del = useDeleteCredential(ws);
  const test = useTestCredential(ws);
  const [results, setResults] = useState<Record<string, CredentialTestResult>>({});
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
              <EmptyState
                compact
                icon={<KeyRound className="h-5 w-5" />}
                title="아직 등록된 연결 정보가 없어요"
                description="오른쪽에서 서비스를 고르고 키·토큰을 넣으면 흐름의 연결 단계에서 고를 수 있어요. 값은 암호화돼 다시 보이지 않아요."
              />
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
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={test.isPending && test.variables === c.id}
                    onClick={() =>
                      test.mutate(c.id, {
                        onSuccess: (r) => setResults((m) => ({ ...m, [c.id]: r })),
                        onError: (err) => toast.error(err),
                      })
                    }
                  >
                    <PlugZap className="h-3.5 w-3.5" />
                    {test.isPending && test.variables === c.id ? "확인 중…" : "연결 테스트"}
                  </Button>
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
                  {c.connector_key === "mcp_server" && <McpToolsButton ws={ws} id={c.id} />}
                  {results[c.id] && <TestResult r={results[c.id] as CredentialTestResult} />}
                </li>
              ))}
            </ul>
            {(creds.data ?? []).length > 0 && (
              <ListPager c={cc} className="border-t border-slate-100 px-5 py-2.5" />
            )}
          </CardBody>
        </Card>
        <div className="space-y-6">
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
          {manage && <McpServerCard ws={ws} />}
          {manage && <ApiToolImportCard ws={ws} />}
          {manage && <PrivateHostsCard ws={ws} />}
        </div>
      </div>
    </PageContainer>
  );
}
