// 외부 호출(HTTP) 단계: 설정한 요청을 한 번 보내 응답을 미리 본다(기능 정의서 §4 응답 미리보기).
// 주소·헤더·본문에 끌어온 값({{...}})이 있으면 시험용 값을 적게 한다.
import { Send } from "lucide-react";
import { useMemo, useState } from "react";
import { DataView } from "@/components/DataView";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { fillRefs, refsIn } from "@/components/canvas/httpPreviewRefs";
import { useHttpPreview, type HttpAuth } from "@/lib/api/v5b";
import { useSession } from "@/store/session";

export function HttpPreview({ data }: { data: Record<string, unknown> }) {
  const { workspaceId } = useSession();
  const preview = useHttpPreview(workspaceId);
  const [open, setOpen] = useState(false);
  const [samples, setSamples] = useState<Record<string, string>>({});
  const refs = useMemo(
    () => refsIn([data.url, data.headers, data.body]),
    [data.url, data.headers, data.body],
  );

  const send = () => {
    const auth = data.auth as HttpAuth | undefined;
    preview.mutate({
      method: String(data.method || "GET"),
      url: fillRefs(String(data.url ?? ""), samples) as string,
      headers: (fillRefs(data.headers ?? {}, samples) as Record<string, string>) || {},
      body: fillRefs(data.body ?? null, samples),
      auth: auth && auth.type !== "none" ? auth : null,
    });
  };

  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)} disabled={!data.url}>
        <Send className="h-3.5 w-3.5" /> 시험 호출
      </Button>
      <Dialog open={open} onClose={() => setOpen(false)} title="시험 호출" wide>
        <div className="space-y-3 text-sm">
          <p className="text-slate-600">
            설정한 요청을 한 번 보내 응답을 미리 봐요. 실행 기록에는 남지 않아요.
          </p>
          <p className="break-all rounded-lg bg-slate-50 px-3 py-2 font-mono text-xs">
            {String(data.method || "GET")} {String(data.url ?? "")}
          </p>
          {refs.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-medium text-slate-600">
                앞 단계에서 끌어온 값은 시험용 값을 적어 주세요.
              </p>
              {refs.map((r) => (
                <label key={r} className="flex items-center gap-2 text-xs">
                  <code className="min-w-0 max-w-[45%] truncate rounded bg-slate-100 px-1.5 py-0.5">
                    {r}
                  </code>
                  <input
                    value={samples[r] ?? ""}
                    onChange={(e) => setSamples((s) => ({ ...s, [r]: e.target.value }))}
                    className="h-8 min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-2"
                    aria-label={`${r} 시험용 값`}
                  />
                </label>
              ))}
            </div>
          )}
          <Button onClick={send} disabled={preview.isPending}>
            <Send className="h-3.5 w-3.5" /> {preview.isPending ? "보내는 중…" : "보내기"}
          </Button>
          <ErrorBox error={preview.error} />
          {preview.data && (
            <div className="space-y-2">
              <p className="text-xs text-slate-600">
                응답 <b>{preview.data.status}</b> · {preview.data.elapsed_ms}ms
                {preview.data.truncated && " · 길어서 앞부분만 보여요"}
              </p>
              <DataView value={preview.data.body} />
            </div>
          )}
        </div>
      </Dialog>
    </>
  );
}
