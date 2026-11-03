import {
  LayoutTemplate,
  MessageSquareText,
  Plug,
  Puzzle,
  Search,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, Empty, PageHeader } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toast-store";
import { ko } from "@/i18n/ko";
import { useInstallations, useMarketItems, useUninstall } from "@/lib/api/resources";
import type { MarketType } from "@/lib/api/types";
import { cn, formatDate } from "@/lib/cn";

const FALLBACK_ICON = { Icon: Puzzle, tile: "bg-slate-100 text-slate-600" };
const TYPE_ICON: Record<string, { Icon: LucideIcon; tile: string }> = {
  connector: { Icon: Plug, tile: "bg-sky-50 text-sky-600" },
  template: { Icon: LayoutTemplate, tile: "bg-indigo-50 text-indigo-600" },
  node: { Icon: Puzzle, tile: "bg-pink-50 text-pink-600" },
  prompt_pack: { Icon: MessageSquareText, tile: "bg-amber-50 text-amber-700" },
};
import { canManage, useSession } from "@/store/session";

function Installed({ ws }: { ws: string }) {
  const role = useSession((s) => s.role);
  const list = useInstallations(ws);
  const uninstall = useUninstall(ws);
  if (list.isLoading) return <Loading />;
  if (list.error) return <ErrorBox error={list.error} />;
  if (!list.data?.length) return <Empty>아직 설치한 아이템이 없어요.</Empty>;
  return (
    <Card className="overflow-hidden">
      <ul className="divide-y divide-slate-100">
        {list.data.map((i) => (
          <li key={i.id} className="flex items-center gap-3 px-5 py-3 text-sm">
            <Badge tone="indigo">{ko.marketTypes[i.type] ?? i.type}</Badge>
            <Link to={`/market/${i.item_key}`} className="font-medium hover:underline">
              {i.item_name}
            </Link>
            <span className="text-xs text-slate-400">v{i.version}</span>
            <StatusBadge status={i.status} />
            <span className="ml-auto text-xs text-slate-400">{formatDate(i.installed_at)}</span>
            {canManage(role) && (
              <Button
                size="sm"
                variant="ghost"
                className="text-red-600"
                onClick={() => {
                  if (
                    window.confirm(
                      `'${i.item_name}'을(를) 제거할까요? 이 아이템을 쓰는 흐름은 동작하지 않게 돼요.`,
                    )
                  ) {
                    uninstall.mutate(i.id, {
                      onSuccess: () => toast.success("제거했어요."),
                      onError: (err) => toast.error(err),
                    });
                  }
                }}
              >
                제거
              </Button>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default function MarketPage() {
  const ws = useSession((s) => s.workspaceId);
  const [params, setParams] = useSearchParams();
  const type = params.get("type") ?? "";
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<"all" | "installed">("all");
  const items = useMarketItems(ws, { type: type || undefined, q: q || undefined });

  return (
    <PageContainer>
      <PageHeader title="마켓" description="필요한 서비스 연결·노드·템플릿을 설치해서 바로 써요." />
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { value: "all", label: "둘러보기" },
          { value: "installed", label: "설치됨" },
        ]}
      />
      {tab === "installed" ? (
        <Installed ws={ws} />
      ) : (
        <>
          <div className="mb-5 flex flex-wrap items-center gap-2">
            {[
              { key: "", label: "전체" },
              ...(Object.keys(ko.marketTypes) as MarketType[]).map((t) => ({
                key: t,
                label: ko.marketTypes[t],
              })),
            ].map((c) => (
              <button
                key={c.key || "all"}
                type="button"
                onClick={() => {
                  const next = new URLSearchParams(params);
                  if (c.key) next.set("type", c.key);
                  else next.delete("type");
                  setParams(next);
                }}
                className={cn(
                  "rounded-full border px-3.5 py-1.5 text-[13px] font-medium transition-colors",
                  type === c.key
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 bg-white text-slate-600 hover:border-slate-300",
                )}
              >
                {c.label}
              </button>
            ))}
            <div className="ml-auto flex w-64 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-sm focus-within:border-indigo-400">
              <Search className="h-4 w-4 text-slate-400" />
              <input
                aria-label="검색"
                className="w-full bg-transparent text-sm placeholder:text-slate-400 focus:outline-none"
                placeholder="이름·설명 검색"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </div>
          </div>
          {items.isLoading && <Loading />}
          <ErrorBox error={items.error} />
          {items.data?.length === 0 && <Empty>조건에 맞는 아이템이 없어요.</Empty>}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {(items.data ?? []).map((it) => (
              <Link key={it.key} to={`/market/${it.key}`}>
                <Card className="flex h-full flex-col p-4 transition-all hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-lift">
                  <div className="flex items-start gap-3">
                    {(() => {
                      const t = TYPE_ICON[it.type] ?? FALLBACK_ICON;
                      return (
                        <span
                          className={cn(
                            "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl",
                            t.tile,
                          )}
                        >
                          <t.Icon className="h-5 w-5" />
                        </span>
                      );
                    })()}
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-semibold text-slate-900">{it.name}</p>
                      <p className="text-xs text-slate-500">{ko.marketTypes[it.type] ?? it.type}</p>
                    </div>
                    {it.installed ? (
                      <Badge tone="green">설치됨</Badge>
                    ) : (
                      <span className="text-xs font-medium text-slate-500">
                        {it.price > 0 ? `${it.price.toLocaleString()}원` : "무료"}
                      </span>
                    )}
                  </div>
                  <p className="mt-3 line-clamp-2 flex-1 text-[13px] leading-relaxed text-slate-600">
                    {it.summary}
                  </p>
                  <p className="mt-3 text-[11px] text-slate-400">
                    {it.publisher} · v{it.version} · 설치 {it.installs}회
                  </p>
                </Card>
              </Link>
            ))}
          </div>
        </>
      )}
    </PageContainer>
  );
}
