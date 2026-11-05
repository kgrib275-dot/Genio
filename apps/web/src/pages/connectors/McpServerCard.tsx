// 연결 정보 화면: MCP 서버 연결하기(주소·토큰 저장 → 연결 테스트로 도구 목록 확인)
import { CheckCircle2, PlugZap, Wrench, XCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { fetchMcpTools, useCreateMcpServer, type McpToolsResult } from "@/lib/api/v8tools";

/** 도구 이름과 설명을 보여 주는 목록(연결 테스트 결과) */
export function McpToolList({ result }: { result: McpToolsResult }) {
  return (
    <div
      role="status"
      className={`basis-full rounded-md px-3 py-2 text-xs ${
        result.ok ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800"
      }`}
    >
      <p className="inline-flex items-center gap-1 font-medium">
        {result.ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
        {result.message}
      </p>
      {result.tools.length > 0 && (
        <ul className="mt-1.5 max-h-48 space-y-1 overflow-y-auto">
          {result.tools.map((t) => (
            <li key={t.name} className="leading-snug">
              <code className="rounded bg-white/60 px-1 font-mono">{t.name}</code>
              {t.description && <span className="ml-1.5 opacity-80">{t.description}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** 등록된 MCP 연결 정보 줄에 붙이는 '도구 보기' 버튼 */
export function McpToolsButton({ ws, id }: { ws: string; id: string }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<McpToolsResult | null>(null);
  return (
    <>
      <Button
        size="sm"
        variant="outline"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            setResult(await fetchMcpTools(ws, id, true));
          } catch (err) {
            toast.error(err);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Wrench className="h-3.5 w-3.5" /> {busy ? "불러오는 중…" : "도구 보기"}
      </Button>
      {result && <McpToolList result={result} />}
    </>
  );
}

export function McpServerCard({ ws }: { ws: string }) {
  const create = useCreateMcpServer(ws);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [header, setHeader] = useState("");
  const [result, setResult] = useState<McpToolsResult | null>(null);
  const [testing, setTesting] = useState(false);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setResult(null);
    create.mutate(
      { name, url, token: token || undefined, header_name: header || undefined },
      {
        onSuccess: async (made) => {
          toast.success(
            "MCP 서버를 연결 정보로 저장했어요. 주소와 토큰은 암호화되어 다시 볼 수 없어요.",
          );
          setName("");
          setUrl("");
          setToken("");
          setHeader("");
          setTesting(true);
          try {
            setResult(await fetchMcpTools(ws, made.id, true));
          } catch (err) {
            toast.error(err);
          } finally {
            setTesting(false);
          }
        },
      },
    );
  };

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-1.5">
            <PlugZap className="h-4 w-4 text-slate-400" /> MCP 서버 연결하기
          </span>
        }
        description="외부 MCP 서버의 도구를 흐름의 '외부 도구 호출(MCP)' 단계와 에이전트에서 쓸 수 있어요."
      />
      <CardBody>
        <form onSubmit={submit} className="space-y-3">
          <Field
            label="이름"
            htmlFor="mcp-name"
            hint="흐름에서 고를 때 보이는 이름이에요. 예: 사내 문서 도구"
          >
            <Input id="mcp-name" required value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field
            label="서버 주소"
            htmlFor="mcp-url"
            hint="서버 설명서의 MCP 주소예요. 예: https://mcp.example.com/mcp"
          >
            <Input
              id="mcp-url"
              required
              type="url"
              autoComplete="off"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </Field>
          <Field label="접속 토큰 (선택)" htmlFor="mcp-token">
            <Input
              id="mcp-token"
              type="password"
              autoComplete="off"
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </Field>
          <Field
            label="토큰을 보낼 헤더 이름 (선택)"
            htmlFor="mcp-header"
            hint="비우면 Authorization: Bearer 로 보내요. 예: X-API-Key"
          >
            <Input id="mcp-header" value={header} onChange={(e) => setHeader(e.target.value)} />
          </Field>
          <ErrorBox error={create.error} />
          <Button type="submit" disabled={create.isPending || testing || !name || !url}>
            {create.isPending ? "저장하는 중…" : testing ? "연결 확인 중…" : "저장하고 연결 테스트"}
          </Button>
        </form>
        {result && (
          <div className="mt-3">
            <McpToolList result={result} />
          </div>
        )}
      </CardBody>
    </Card>
  );
}
