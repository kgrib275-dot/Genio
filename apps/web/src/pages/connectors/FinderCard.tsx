// 새 서비스 찾기: MCP 서비스 검색과 n8n 템플릿 가져오기를 탭 하나로 묶는다(ADR 0020)
import { Search } from "lucide-react";
import { useState } from "react";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { CatalogCard } from "@/pages/connectors/CatalogCard";
import { N8nCard } from "@/pages/connectors/N8nCard";
import { TrendsPanel } from "@/pages/connectors/TrendsPanel";

const TABS = [
  {
    id: "new",
    label: "이번 주 새 소식",
    hint: "이번 주에 새로 나온 서비스와 많이 쓰는 템플릿을 한눈에 보고 바로 써 봐요.",
  },
  { id: "mcp", label: "서비스 연결", hint: "공식 MCP 목록에서 최신 서비스를 찾아 바로 연결해요." },
  { id: "n8n", label: "n8n 템플릿", hint: "n8n의 공개 무료 템플릿을 제니오 초안 앱으로 가져와요." },
] as const;

export function FinderCard({ ws }: { ws: string }) {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("new");
  const current = TABS.find((t) => t.id === tab) ?? TABS[0];
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-1.5">
            <Search className="h-4 w-4 text-slate-400" /> 새 서비스 찾기
          </span>
        }
        description={current.hint}
      />
      <CardBody className="space-y-3">
        <div
          role="tablist"
          aria-label="찾는 방법"
          className="flex gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800"
        >
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition",
                tab === t.id
                  ? "bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white"
                  : "text-slate-500 hover:text-slate-700 dark:hover:text-slate-200",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
        {tab === "new" && <TrendsPanel ws={ws} />}
        {tab === "mcp" && <CatalogCard ws={ws} bare />}
        {tab === "n8n" && <N8nCard ws={ws} bare />}
      </CardBody>
    </Card>
  );
}
