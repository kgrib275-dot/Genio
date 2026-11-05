// v0.8 외부 지식베이스: 내가 운영하는 검색 서비스(Dify 외부 지식 API 모양)를 지식베이스처럼 연결한다.
import { CheckCircle2, PlugZap, XCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { useCredentials } from "@/lib/api/resources";
import {
  externalOf,
  useCreateExternalKb,
  useTestNewExternal,
  useTestSavedExternal,
  useUpdateExternal,
  type ExternalConfig,
  type ExternalTestResult,
} from "@/lib/api/v8kb";
import type { KnowledgeBaseV2 } from "@/lib/api/types";

function TestResult({ r }: { r: ExternalTestResult }) {
  return (
    <div
      role="status"
      className={
        r.ok
          ? "flex gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
          : "flex gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700"
      }
    >
      {r.ok ? (
        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
      ) : (
        <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
      )}
      <span className="min-w-0">
        {r.message}
        {r.hint && <span className="block text-xs opacity-80">{r.hint}</span>}
        {r.ok && r.sample && r.sample.length > 0 && (
          <ul className="mt-1 space-y-0.5 text-xs opacity-90">
            {r.sample.map((x, i) => (
              <li key={i} className="truncate">
                {x.title} · 점수 {x.score.toFixed(2)} · {x.content}
              </li>
            ))}
          </ul>
        )}
      </span>
    </div>
  );
}

/** 주소·지식 id·API 키 입력 칸(만들기와 고치기가 함께 쓴다) */
function ExternalFields({
  ws,
  value,
  onChange,
}: {
  ws: string;
  value: ExternalConfig;
  onChange: (v: ExternalConfig) => void;
}) {
  const creds = useCredentials(ws);
  const keys = (creds.data ?? []).filter((c) => c.connector_key === "http_credentials");
  return (
    <div className="space-y-3">
      <Field
        label="서비스 주소"
        htmlFor="ext-endpoint"
        hint="검색 서비스의 API 주소예요. 끝에 /retrieval을 붙이지 않아도 돼요."
      >
        <Input
          id="ext-endpoint"
          placeholder="https://rag.example.com/api"
          value={value.endpoint}
          onChange={(e) => onChange({ ...value, endpoint: e.target.value })}
        />
      </Field>
      <Field
        label="지식 id"
        htmlFor="ext-kid"
        hint="서비스 안에서 어느 지식을 찾을지 가리키는 값이에요."
      >
        <Input
          id="ext-kid"
          value={value.knowledge_id}
          onChange={(e) => onChange({ ...value, knowledge_id: e.target.value })}
        />
      </Field>
      <Field
        label="API 키(연결 정보)"
        htmlFor="ext-cred"
        hint="'HTTP 인증 정보'에 Bearer 토큰으로 넣어 둔 키를 골라요. 키가 필요 없는 서비스는 비워 두세요."
      >
        <Select
          id="ext-cred"
          value={value.credential_id ?? ""}
          onChange={(e) => onChange({ ...value, credential_id: e.target.value || null })}
        >
          <option value="">키 없음</option>
          {keys.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
      </Field>
      {!creds.isLoading && keys.length === 0 && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
          API 키가 필요하면{" "}
          <Link to="/connectors" className="font-semibold underline">
            연결 정보 화면
          </Link>
          에서 마켓의 'HTTP 인증 정보'를 설치하고 토큰을 넣어 주세요.
        </p>
      )}
    </div>
  );
}

const EMPTY: ExternalConfig = { endpoint: "", knowledge_id: "", credential_id: null };

/** 새 외부 지식베이스 연결 대화상자 */
export function ExternalKbDialog({
  ws,
  projectId,
  onClose,
  onCreated,
}: {
  ws: string;
  projectId?: string;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const [name, setName] = useState("");
  const [ext, setExt] = useState<ExternalConfig>(EMPTY);
  const [result, setResult] = useState<ExternalTestResult | null>(null);
  const test = useTestNewExternal(ws);
  const create = useCreateExternalKb(ws);
  const filled = /^https?:\/\//.test(ext.endpoint.trim()) && ext.knowledge_id.trim() !== "";
  const clean = (): ExternalConfig => ({
    endpoint: ext.endpoint.trim(),
    knowledge_id: ext.knowledge_id.trim(),
    credential_id: ext.credential_id,
  });
  return (
    <Dialog
      open
      onClose={onClose}
      title="외부 지식베이스 연결"
      wide
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            취소
          </Button>
          <Button
            variant="outline"
            disabled={!filled || test.isPending}
            onClick={() =>
              test.mutate(clean(), { onSuccess: setResult, onError: (e) => toast.error(e) })
            }
          >
            <PlugZap className="h-4 w-4" /> {test.isPending ? "확인 중…" : "연결 테스트"}
          </Button>
          <Button
            disabled={!filled || !name.trim() || create.isPending}
            onClick={() =>
              create.mutate(
                { name: name.trim(), project_id: projectId, external: clean() },
                {
                  onSuccess: (k) => {
                    toast.success("연결했어요. '검색 시험'에서 질문해 보세요.");
                    onCreated(k.id);
                  },
                },
              )
            }
          >
            연결하기
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <p className="text-slate-600">
          이미 운영하는 검색 서비스가 있다면 문서를 다시 올리지 않고 그대로 연결해요. 서비스는
          <code className="mx-1 rounded bg-slate-100 px-1 text-xs">POST {"{주소}"}/retrieval</code>
          로 질문을 받아 <code className="rounded bg-slate-100 px-1 text-xs">records</code> 목록을
          돌려줘야 해요.
        </p>
        <Field label="지식베이스 이름" htmlFor="ext-name">
          <Input
            id="ext-name"
            placeholder="예: 회사 RAG 서버"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <ExternalFields ws={ws} value={ext} onChange={setExt} />
        {result && <TestResult r={result} />}
        <ErrorBox error={create.error ?? test.error} />
      </div>
    </Dialog>
  );
}

/** 외부 지식베이스 상세: 연결 확인과 고치기 */
export function ExternalKbCard({
  ws,
  kb,
  editable,
}: {
  ws: string;
  kb: KnowledgeBaseV2;
  editable: boolean;
}) {
  const saved = externalOf(kb) ?? EMPTY;
  const [editing, setEditing] = useState(false);
  const [ext, setExt] = useState<ExternalConfig>(saved);
  const [result, setResult] = useState<ExternalTestResult | null>(null);
  const test = useTestSavedExternal(kb.id);
  const update = useUpdateExternal(kb.id);
  return (
    <Card>
      <CardHeader
        title="외부 지식베이스 연결"
        description="이 지식베이스는 문서를 올리지 않고, 연결한 검색 서비스에 바로 물어봐요."
        action={
          editable && (
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={test.isPending}
                onClick={() =>
                  test.mutate(undefined, { onSuccess: setResult, onError: (e) => toast.error(e) })
                }
              >
                <PlugZap className="h-3.5 w-3.5" /> {test.isPending ? "확인 중…" : "연결 테스트"}
              </Button>
              <Button size="sm" variant="outline" onClick={() => setEditing((v) => !v)}>
                {editing ? "닫기" : "고치기"}
              </Button>
            </div>
          )
        }
      />
      <CardBody className="space-y-3 text-sm">
        {!editing && (
          <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[7rem_1fr]">
            <dt className="text-slate-500">서비스 주소</dt>
            <dd className="break-all font-mono text-xs">{saved.endpoint}</dd>
            <dt className="text-slate-500">지식 id</dt>
            <dd className="font-mono text-xs">{saved.knowledge_id}</dd>
            <dt className="text-slate-500">API 키</dt>
            <dd>{saved.credential_id ? "연결 정보로 보관 중" : "없음"}</dd>
          </dl>
        )}
        {editing && (
          <>
            <ExternalFields ws={ws} value={ext} onChange={setExt} />
            <div className="flex justify-end">
              <Button
                disabled={update.isPending}
                onClick={() =>
                  update.mutate(
                    {
                      ...ext,
                      endpoint: ext.endpoint.trim(),
                      knowledge_id: ext.knowledge_id.trim(),
                    },
                    {
                      onSuccess: () => {
                        toast.success("저장했어요.");
                        setEditing(false);
                      },
                    },
                  )
                }
              >
                저장
              </Button>
            </div>
            <ErrorBox error={update.error} />
          </>
        )}
        {result && <TestResult r={result} />}
      </CardBody>
    </Card>
  );
}
