// 연결 정보 화면: OpenAPI 가져오기 → 도구 고르기 → 기본 주소·인증 정하기 → 저장
import { FileJson } from "lucide-react";
import { useMemo, useState } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { useCredentials } from "@/lib/api/resources";
import {
  useCreateApiToolSet,
  usePreviewApiTools,
  type ApiSpecPreview,
  type NewApiToolSet,
} from "@/lib/api/v8tools";

const AUTH_LABELS: Record<NewApiToolSet["auth_type"], string> = {
  none: "인증 없음",
  bearer: "Bearer 토큰",
  basic: "아이디/비밀번호",
  header: "헤더(API 키)",
};

export function ApiToolImportCard({ ws }: { ws: string }) {
  const preview = usePreviewApiTools(ws);
  const create = useCreateApiToolSet(ws);
  const creds = useCredentials(ws);
  const [mode, setMode] = useState<"url" | "text">("url");
  const [source, setSource] = useState("");
  const [parsed, setParsed] = useState<ApiSpecPreview | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [authType, setAuthType] = useState<NewApiToolSet["auth_type"]>("none");
  const [authCred, setAuthCred] = useState("");
  const [filter, setFilter] = useState("");

  const httpCreds = (creds.data ?? []).filter((c) => c.connector_key === "http_credentials");
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return (parsed?.operations ?? []).filter(
      (o) => !q || `${o.method} ${o.path} ${o.summary} ${o.id}`.toLowerCase().includes(q),
    );
  }, [parsed, filter]);

  const body = mode === "url" ? { url: source.trim() } : { text: source };

  const read = () =>
    preview.mutate(body, {
      onSuccess: (p) => {
        setParsed(p);
        setSelected(new Set(p.operations.map((o) => o.id)));
        setName(p.title || "API 도구");
        setBaseUrl(p.base_url);
      },
    });

  const save = () =>
    create.mutate(
      {
        ...body,
        name,
        base_url: baseUrl || undefined,
        selected: [...selected],
        auth_type: authType,
        auth_credential_id: authType === "none" ? undefined : authCred,
      },
      {
        onSuccess: (r) => {
          toast.success(
            `API 도구 ${r.tools}개를 가져왔어요. 흐름의 'API 도구 호출' 단계에서 쓸 수 있어요.`,
          );
          setParsed(null);
          setSource("");
          setSelected(new Set());
        },
      },
    );

  const ready =
    Boolean(parsed) &&
    selected.size > 0 &&
    name.trim() !== "" &&
    baseUrl.trim() !== "" &&
    (authType === "none" || authCred !== "");

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-1.5">
            <FileJson className="h-4 w-4 text-slate-400" /> API 도구(OpenAPI) 가져오기
          </span>
        }
        description="OpenAPI 3 명세(JSON·YAML)에서 API의 기능을 도구로 가져와요. 최대 1MB, 도구 200개까지예요."
      />
      <CardBody className="space-y-3">
        <div
          role="radiogroup"
          aria-label="명세 가져오는 방법"
          className="inline-flex rounded-lg bg-slate-100 p-1"
        >
          {(["url", "text"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              onClick={() => {
                setMode(m);
                setSource("");
                setParsed(null);
              }}
              className={`rounded-md px-3 py-1 text-sm ${
                mode === m ? "bg-white font-medium shadow-sm" : "text-slate-500"
              }`}
            >
              {m === "url" ? "주소로" : "붙여 넣기"}
            </button>
          ))}
        </div>
        {mode === "url" ? (
          <Field label="명세 주소" htmlFor="oa-url" hint="예: https://api.example.com/openapi.json">
            <Input
              id="oa-url"
              type="url"
              value={source}
              onChange={(e) => setSource(e.target.value)}
            />
          </Field>
        ) : (
          <Field label="명세 내용" htmlFor="oa-text">
            <Textarea
              id="oa-text"
              rows={6}
              className="font-mono text-xs"
              value={source}
              onChange={(e) => setSource(e.target.value)}
            />
          </Field>
        )}
        <ErrorBox error={preview.error} />
        <Button
          size="sm"
          variant="outline"
          disabled={preview.isPending || !source.trim()}
          onClick={read}
        >
          {preview.isPending ? "읽는 중…" : "도구 목록 미리 보기"}
        </Button>

        {parsed && (
          <div className="space-y-3 border-t border-slate-100 pt-3">
            <p className="text-sm text-slate-600">
              <b>{parsed.title || "이름 없는 API"}</b> {parsed.version && `(${parsed.version})`} ·
              도구 {parsed.total}개
              {parsed.truncated && ` 중 앞의 ${parsed.operations.length}개만 보여요`}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                aria-label="도구 찾기"
                placeholder="도구 찾기"
                className="h-8 w-40"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setSelected(new Set(shown.map((o) => o.id)))}
              >
                보이는 것 모두 고르기
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
                모두 빼기
              </Button>
              <span className="text-xs text-slate-500">{selected.size}개 선택</span>
            </div>
            <ul className="max-h-56 divide-y divide-slate-100 overflow-y-auto rounded-md border border-slate-200 text-sm">
              {shown.map((o) => (
                <li key={o.id}>
                  <label className="flex cursor-pointer items-start gap-2 px-3 py-1.5 hover:bg-slate-50">
                    <input
                      type="checkbox"
                      className="mt-1 accent-indigo-600"
                      checked={selected.has(o.id)}
                      onChange={(e) => {
                        const next = new Set(selected);
                        if (e.target.checked) next.add(o.id);
                        else next.delete(o.id);
                        setSelected(next);
                      }}
                    />
                    <span className="min-w-0">
                      <span className="mr-1.5 rounded bg-slate-100 px-1 font-mono text-[11px]">
                        {o.method}
                      </span>
                      <code className="text-xs">{o.path}</code>
                      {o.summary && (
                        <span className="block text-xs text-slate-500">{o.summary}</span>
                      )}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
            <Field label="묶음 이름" htmlFor="oa-name" hint="흐름에서 고를 때 보이는 이름이에요.">
              <Input id="oa-name" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field
              label="기본 주소"
              htmlFor="oa-base"
              hint={
                parsed.base_url
                  ? undefined
                  : "명세에 서버 주소가 없어요. https://로 시작하는 주소를 넣어 주세요."
              }
            >
              <Input
                id="oa-base"
                type="url"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </Field>
            <Field label="인증 방식" htmlFor="oa-auth">
              <Select
                id="oa-auth"
                value={authType}
                onChange={(e) => {
                  setAuthType(e.target.value as NewApiToolSet["auth_type"]);
                  setAuthCred("");
                }}
              >
                {Object.entries(AUTH_LABELS).map(([k, label]) => (
                  <option key={k} value={k}>
                    {label}
                  </option>
                ))}
              </Select>
            </Field>
            {authType !== "none" && (
              <Field
                label="HTTP 인증 정보"
                htmlFor="oa-cred"
                hint={
                  httpCreds.length === 0
                    ? "'HTTP 인증 정보' 연결 정보가 없어요. 위 '새 연결 정보'에서 먼저 만들어 주세요."
                    : "토큰·비밀번호는 여기에 적지 않고 연결 정보에서 꺼내 써요."
                }
              >
                <Select id="oa-cred" value={authCred} onChange={(e) => setAuthCred(e.target.value)}>
                  <option value="">연결 정보 선택</option>
                  {httpCreds.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            <ErrorBox error={create.error} />
            <Button disabled={!ready || create.isPending} onClick={save}>
              {create.isPending ? "저장하는 중…" : `도구 ${selected.size}개 가져오기`}
            </Button>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
