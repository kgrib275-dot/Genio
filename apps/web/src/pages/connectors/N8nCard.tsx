// n8n 공개 템플릿 찾기: 검색해서 제니오 초안 앱으로 가져온다(ADR 0020 2단계)
import { ExternalLink, Workflow } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ErrorBox } from "@/components/ErrorBox";
import { DifyReportView } from "@/components/dify/DifyImportDialog";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  fetchN8n,
  useCatalogEnabled,
  useImportN8n,
  type N8nPage,
  type N8nTemplate,
} from "@/lib/api/catalog";
import type { DifyImportResult } from "@/lib/api/difyImport";

export function N8nCard({ ws }: { ws: string }) {
  const enabled = useCatalogEnabled(ws);
  const imp = useImportN8n(ws);
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [last, setLast] = useState("");
  const [page, setPage] = useState<N8nPage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<DifyImportResult | null>(null);
  const [importing, setImporting] = useState<number | null>(null);

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

  const take = (t: N8nTemplate) => {
    setImporting(t.id);
    imp.mutate(t.id, {
      onSuccess: setResult,
      onSettled: () => setImporting(null),
    });
  };

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
      <CardBody className="space-y-3">
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
            <ErrorBox error={error ?? imp.error} />
            {page && page.items.length === 0 && (
              <p className="text-sm text-slate-500">
                찾은 템플릿이 없어요. 다른 말로 검색해 보세요.
              </p>
            )}
            {page && page.items.length > 0 && (
              <ul className="max-h-[28rem] space-y-2 overflow-y-auto">
                {page.items.map((t) => (
                  <li key={t.id} className="space-y-1 rounded-lg border border-slate-200 p-3">
                    <div className="flex flex-wrap items-start gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium">{t.name}</p>
                        <p className="text-xs text-slate-500">{t.description}</p>
                        <p className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                          <span>조회 {t.views.toLocaleString()}</span>
                          {t.author && <span>작성 {t.author}</span>}
                          <a
                            href={t.url}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="inline-flex items-center gap-0.5 hover:underline"
                          >
                            원본 <ExternalLink className="h-3 w-3" />
                          </a>
                        </p>
                        {t.services.length > 0 && (
                          <p className="mt-0.5 text-[11px] text-slate-500">
                            쓰는 서비스: {t.services.join(", ")}
                          </p>
                        )}
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={importing !== null}
                        onClick={() => take(t)}
                      >
                        {importing === t.id ? "가져오는 중…" : "가져오기"}
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
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
      </CardBody>
      <Dialog
        open={result !== null}
        onClose={() => setResult(null)}
        title="가져오기 결과"
        wide
        footer={
          <>
            <Button variant="ghost" onClick={() => setResult(null)}>
              닫기
            </Button>
            <Button
              onClick={() => {
                const id = result?.app.id;
                setResult(null);
                if (id) navigate(`/apps/${id}/builder`);
              }}
            >
              빌더에서 열기
            </Button>
          </>
        }
      >
        {result && <DifyReportView result={result} />}
      </Dialog>
    </Card>
  );
}
