// 웹 요청 블록: cURL 명령을 붙여 넣으면 방식·주소·헤더·본문을 채운다.
import { ClipboardPaste } from "lucide-react";
import { useState } from "react";
import { parseCurl } from "@/components/canvas/curl";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";

export function CurlImport({
  data,
  onChange,
  disabled,
}: {
  data: Record<string, unknown>;
  onChange: (data: Record<string, unknown>) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [error, setError] = useState(false);

  const apply = () => {
    const r = parseCurl(text);
    if (!r) {
      setError(true);
      return;
    }
    const { headers: _h, body: _b, ...rest } = data;
    void _h;
    void _b;
    const next: Record<string, unknown> = { ...rest, method: r.method, url: r.url };
    if (Object.keys(r.headers).length) next.headers = r.headers;
    if (r.body !== undefined) next.body = r.body;
    onChange(next);
    setOpen(false);
    setText("");
  };

  return (
    <>
      <Button
        size="sm"
        variant="outline"
        className="mb-3 w-full"
        disabled={disabled}
        onClick={() => {
          setError(false);
          setOpen(true);
        }}
      >
        <ClipboardPaste className="h-3.5 w-3.5" /> cURL 붙여넣기
      </Button>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="cURL 붙여넣기"
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>
              취소
            </Button>
            <Button onClick={apply} disabled={!text.trim()}>
              채우기
            </Button>
          </>
        }
      >
        <p className="mb-2 text-sm text-slate-500">
          API 문서나 브라우저 개발자 도구에서 복사한 cURL 명령을 붙여 넣으면 방식·주소·헤더·본문을
          채워요. 지금 설정은 덮어써요.
        </p>
        <textarea
          aria-label="cURL 명령"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setError(false);
          }}
          placeholder={`curl -X POST https://api.example.com/items \\\n  -H "Content-Type: application/json" \\\n  -d '{"name": "사과"}'`}
          className="min-h-[160px] w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 font-mono text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
        {error && (
          <div role="alert" className="mt-2 text-xs text-red-700">
            <p>cURL 명령을 읽지 못했어요.</p>
            <p className="text-red-600/80">
              curl로 시작하고 주소(https://…)가 들어 있는지 확인한 뒤 다시 붙여 넣으세요.
            </p>
          </div>
        )}
      </Dialog>
    </>
  );
}
