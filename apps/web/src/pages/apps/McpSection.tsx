// MCP로 게시(v0.6): 이 앱을 Claude 데스크톱 같은 MCP 클라이언트에서 도구 하나로 부른다
import { Copy, Plug } from "lucide-react";
import { useEffect, useState } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { ko } from "@/i18n/ko";
import { useApp } from "@/lib/api/apps";
import type { AppDetailV2 } from "@/lib/api/types";
import { mcpConfigSnippets, mcpOf, previewToolName, useSaveMcp } from "@/lib/api/v6mcp";
import { copyText } from "@/lib/cn";

function Snippet({ title, code }: { title: string; code: string }) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-slate-600">{title}</p>
      <div className="group relative">
        <pre className="overflow-x-auto rounded-xl bg-slate-900 px-4 py-3 font-mono text-[12px] leading-relaxed text-slate-100">
          {code}
        </pre>
        <button
          type="button"
          aria-label={`${title} 복사`}
          className="absolute right-2 top-2 rounded-md bg-white/10 p-1.5 text-slate-200 opacity-80 hover:bg-white/20 group-hover:opacity-100"
          onClick={async () => {
            if (await copyText(code)) toast.success(ko.common.copied);
          }}
        >
          <Copy className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

export function McpSection({ appId }: { appId: string }) {
  const app = useApp(appId);
  const detail = app.data as AppDetailV2 | undefined;
  const saved = mcpOf(detail);
  const save = useSaveMcp(appId);
  const [toolName, setToolName] = useState("");
  const [description, setDescription] = useState("");
  useEffect(() => {
    setToolName(saved.tool_name);
    setDescription(saved.description);
  }, [saved.tool_name, saved.description]);

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const url = `${origin}/api/v1/service/mcp`;
  const name = previewToolName(detail?.name ?? "", appId, toolName);
  const snippets = mcpConfigSnippets(url, "gk-여기에_MCP_권한_키", `genio-${name}`);

  const update = (enabled: boolean) =>
    save.mutate(
      { enabled, tool_name: toolName.trim(), description: description.trim() },
      {
        onSuccess: () =>
          toast.success(enabled ? "MCP 게시 설정을 저장했어요." : "MCP 게시를 껐어요."),
        onError: (err) => toast.error(err),
      },
    );

  return (
    <Card>
      <CardHeader
        title="MCP로 게시"
        description="Claude 데스크톱 같은 AI 도우미가 이 앱을 도구 하나로 불러 쓸 수 있어요."
      />
      <CardBody className="space-y-4 text-sm">
        <div className="flex flex-wrap items-center gap-3">
          <Plug className={saved.enabled ? "h-5 w-5 text-emerald-600" : "h-5 w-5 text-slate-400"} />
          <span className="font-medium">
            {saved.enabled ? "게시 중이에요" : "아직 게시하지 않았어요"}
          </span>
          <Button
            size="sm"
            variant={saved.enabled ? "outline" : "primary"}
            disabled={save.isPending}
            onClick={() => update(!saved.enabled)}
          >
            {saved.enabled ? "게시 끄기" : "MCP로 게시하기"}
          </Button>
        </div>
        <ErrorBox error={save.error} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="도구 이름(영문·숫자)"
            htmlFor="mcp-name"
            hint={`AI 도우미에게 보이는 이름: ${name}`}
          >
            <Input
              id="mcp-name"
              placeholder="비우면 앱 이름에서 만들어요"
              value={toolName}
              onChange={(e) => setToolName(e.target.value)}
            />
          </Field>
          <Field
            label="도구 설명"
            htmlFor="mcp-desc"
            hint="언제 이 도구를 쓰면 좋은지 적어 주세요."
          >
            <Input
              id="mcp-desc"
              placeholder={detail?.description || "예: 사내 규정을 찾아 답해요"}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
        </div>
        {saved.enabled && (
          <Button
            size="sm"
            variant="outline"
            disabled={save.isPending}
            onClick={() => update(true)}
          >
            이름·설명 저장
          </Button>
        )}
        <ol className="list-decimal space-y-1 pl-5 text-slate-600">
          <li>
            위 <b>API 키</b>에서 <b>MCP 도구</b> 권한을 켜고 키를 만들어요.
          </li>
          <li>AI 도우미 설정에 아래 내용을 넣고, 키 자리에 만든 키를 넣어요.</li>
          <li>도우미에게 “{name} 도구로 …해 줘”라고 부탁하면 이 앱이 실행돼요.</li>
        </ol>
        <Field label="MCP 주소" htmlFor="mcp-url">
          <Input id="mcp-url" readOnly value={url} className="font-mono text-xs" />
        </Field>
        <Snippet title="Claude 데스크톱(claude_desktop_config.json)" code={snippets.desktop} />
        <Snippet title="HTTP 연결을 바로 쓰는 도구(Cursor 등)" code={snippets.http} />
        <Snippet title="Claude Code 명령" code={snippets.cli} />
        <p className="text-xs text-slate-500">
          저장한 최신 버전이 실행돼요. 사람 승인을 기다리는 흐름은 결과 대신 &quot;기다리는
          중&quot;을 알려 줘요. 한 번 부를 때 최대 60초를 기다려요.
        </p>
      </CardBody>
    </Card>
  );
}
