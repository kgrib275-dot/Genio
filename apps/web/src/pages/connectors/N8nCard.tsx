// n8n 공개 템플릿 찾기: 검색해서 제니오 초안 앱으로 가져온다(ADR 0020 2단계)
import { Workflow } from "lucide-react";
import { useState } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { fetchN8n, useCatalogEnabled, type N8nPage } from "@/lib/api/catalog";
import { N8nList } from "@/pages/connectors/N8nList";

export function N8nCard({ ws, bare = false }: { ws: string; bare?: boolean }) {
  const enabled = useCatalogEnabled(ws);
  const [q, setQ] = useState("");
  const [last, setLast] = useState("");
  const [page, setPage] = useState<N8nPage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const run = async (query: string, n = 1) => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetchN8n(ws, query, n);
      setPage(n > 1 && page ? { ...res, items: [...page.items, ...res.items] } : res);
      setLast(query);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const body = (
    <div className="space-y-3">
      {enabled.data && !enabled.data.external_catalog ? (
        <p className="text-sm text-slate-600">
          이 회사는 아직 켜지 않았어요. 소유자나 관리자가{" "}
          <b>관리 &gt; 안전·규칙 &gt; 외부 서비스 찾기</b>를 켜면 쓸 수 있어요.
        </p>
      ) : (
        <>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void run(q.trim());
            }}
          >
            <Input
              aria-label="n8n 템플릿 검색"
              placeholder="예: 슬랙 알림, 메일 요약, google sheets"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <Button type="submit" disabled={busy}>
              {busy ? "찾는 중…" : "찾기"}
            </Button>
          </form>
          <ErrorBox error={error} />
          {page && page.items.length === 0 && (
            <p className="text-sm text-slate-500">찾은 템플릿이 없어요. 다른 말로 검색해 보세요.</p>
          )}
          {page && page.items.length > 0 && <N8nList ws={ws} items={page.items} />}
          {page?.has_more && (
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => void run(last, page.page + 1)}
            >
              더 보기
            </Button>
          )}
        </>
      )}
    </div>
  );
  if (bare) return body;
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-1.5">
            <Workflow className="h-4 w-4 text-slate-400" /> n8n 템플릿 가져오기
          </span>
        }
        description="n8n의 공개 무료 템플릿을 찾아 제니오 초안 앱으로 만들어요. 웹 요청과 시작·결과 단계만 옮기고, 나머지는 꺼진 자리 표시로 남아요."
      />
      <CardBody>{body}</CardBody>
    </Card>
  );
}
