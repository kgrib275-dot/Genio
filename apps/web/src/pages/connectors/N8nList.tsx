// n8n 템플릿 목록과 '가져오기'(검색 결과·트렌드 목록이 함께 쓴다)
import { ExternalLink } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ErrorBox } from "@/components/ErrorBox";
import { DifyReportView } from "@/components/dify/DifyImportDialog";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useImportN8n, type N8nTemplate } from "@/lib/api/catalog";
import type { DifyImportResult } from "@/lib/api/difyImport";

export function N8nList({ ws, items }: { ws: string; items: N8nTemplate[] }) {
  const imp = useImportN8n(ws);
  const navigate = useNavigate();
  const [result, setResult] = useState<DifyImportResult | null>(null);
  const [importing, setImporting] = useState<number | null>(null);

  const take = (t: N8nTemplate) => {
    setImporting(t.id);
    imp.mutate(t.id, {
      onSuccess: setResult,
      onSettled: () => setImporting(null),
    });
  };

  return (
    <>
      <ErrorBox error={imp.error} />
      <ul className="max-h-[28rem] space-y-2 overflow-y-auto">
        {items.map((t) => (
          <li key={t.id} className="space-y-1 rounded-lg border border-slate-200 p-3">
            <div className="flex flex-wrap items-start gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{t.name}</p>
                <p className="text-xs text-slate-500">{t.description}</p>
                <p className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                  <span>조회 {t.views.toLocaleString()}</span>
                  {t.author && <span>작성 {t.author}</span>}
                  {t.created_at && <span>{t.created_at.slice(0, 10)}</span>}
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
    </>
  );
}
