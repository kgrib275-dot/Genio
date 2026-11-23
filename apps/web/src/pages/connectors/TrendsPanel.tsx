// 이번 주 새로 나온 것: 하루 한 번 모아 둔 새 MCP 서비스와 n8n 최신·인기 템플릿(ADR 0020)
import { Flame, Sparkles } from "lucide-react";
import { ErrorBox } from "@/components/ErrorBox";
import { useCatalogEnabled, useTrends } from "@/lib/api/catalog";
import { CatalogRow } from "@/pages/connectors/CatalogCard";
import { N8nList } from "@/pages/connectors/N8nList";

function when(iso: string): string {
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "";
  return t.toLocaleString("ko-KR", {
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function TrendsPanel({ ws }: { ws: string }) {
  const enabled = useCatalogEnabled(ws);
  const on = Boolean(enabled.data?.external_catalog);
  const q = useTrends(ws, on);

  if (enabled.data && !enabled.data.external_catalog) {
    return (
      <p className="text-sm text-slate-600">
        이 회사는 아직 켜지 않았어요. 소유자나 관리자가{" "}
        <b>관리 &gt; 안전·규칙 &gt; 외부 서비스 찾기</b>를 켜면 쓸 수 있어요.
      </p>
    );
  }
  if (q.isLoading) return <p className="text-sm text-slate-500">새 소식을 불러오는 중이에요…</p>;
  const d = q.data;
  return (
    <div className="space-y-5">
      <ErrorBox error={q.error} />
      {d && (
        <>
          <p className="text-xs text-slate-500">
            {d.updated_at
              ? `${when(d.updated_at)}에 모아 둔 목록이에요. 하루에 한 번 새로 모아요.`
              : "아직 모은 목록이 없어요."}
            {d.mcp_new_today > 0 && (
              <b className="ml-1 text-indigo-600">오늘 새로 올라온 서비스 {d.mcp_new_today}개</b>
            )}
          </p>
          {d.errors.length > 0 && (
            <p role="note" className="rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-800">
              일부 목록은 이번에 못 가져왔어요({d.errors.join(" · ")}). 있는 만큼 보여 드려요.
            </p>
          )}
          <section className="space-y-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold">
              <Sparkles className="h-4 w-4 text-indigo-500" /> 이번 주 새 서비스(MCP)
              <span className="text-xs font-normal text-slate-400">
                바로 연결할 수 있는 것만 · 전체 {d.mcp_new_total}개 중
              </span>
            </h3>
            {d.mcp_new.length === 0 ? (
              <p className="text-sm text-slate-500">이번 주에 새로 올라온 서비스가 없어요.</p>
            ) : (
              <ul className="max-h-[22rem] space-y-2 overflow-y-auto">
                {d.mcp_new.map((it) => (
                  <CatalogRow key={it.name} ws={ws} item={it} />
                ))}
              </ul>
            )}
          </section>
          <section className="space-y-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold">
              <Sparkles className="h-4 w-4 text-emerald-500" /> 새로 올라온 n8n 템플릿
            </h3>
            {d.n8n_new.length === 0 ? (
              <p className="text-sm text-slate-500">불러온 템플릿이 없어요.</p>
            ) : (
              <N8nList ws={ws} items={d.n8n_new} />
            )}
          </section>
          <section className="space-y-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold">
              <Flame className="h-4 w-4 text-orange-500" /> 많이 쓰는 n8n 템플릿
              <span className="text-xs font-normal text-slate-400">조회가 많은 순</span>
            </h3>
            {d.n8n_popular.length === 0 ? (
              <p className="text-sm text-slate-500">불러온 템플릿이 없어요.</p>
            ) : (
              <N8nList ws={ws} items={d.n8n_popular} />
            )}
          </section>
          <p className="text-[11px] text-slate-400">
            누구나 올릴 수 있는 공개 목록이에요. 인기·최신 순서일 뿐 품질을 보증하지 않으니, 출처를
            보고 골라 주세요.
          </p>
        </>
      )}
    </div>
  );
}
