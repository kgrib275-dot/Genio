import { HelpButton } from "@/help/HelpButton";
import { LayoutTemplate, MessageSquareText, Plug, Puzzle, type LucideIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, Empty, PageHeader } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toast-store";
import { ko } from "@/i18n/ko";
import { useInstallations, useMarketItems, useUninstall } from "@/lib/api/resources";
import { useInstallationsV5, useUpdateInstallation } from "@/lib/api/v5b";
import type { MarketType } from "@/lib/api/types";
import { cn, formatDate } from "@/lib/cn";
import { SORTS, sortItems, type SortKey } from "@/lib/marketSort";
import { optionsFrom, useListControls } from "@/lib/useListControls";

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
  const latest = useInstallationsV5(ws);
  const update = useUpdateInstallation(ws);
  const updates = new Map((latest.data ?? []).map((i) => [i.id, i]));
  const c = useListControls(list.data, {
    key: "market-installed",
    search: (i) => `${i.item_name} ${i.item_key}`,
    filters: [
      {
        id: "type",
        label: "종류",
        options: (Object.keys(ko.marketTypes) as MarketType[]).map((t) => ({
          value: t,
          label: ko.marketTypes[t],
        })),
        match: (i, v) => i.type === v,
      },
    ],
  });
  if (list.isLoading) return <Loading />;
  if (list.error) return <ErrorBox error={list.error} />;
  if (!list.data?.length) return <Empty>아직 설치한 아이템이 없어요.</Empty>;
  return (
    <Card className="overflow-hidden">
      <ListToolbar
        c={c}
        placeholder="설치한 아이템 찾기"
        className="border-b border-slate-100 p-3 sm:px-5"
      />
      <NoMatch c={c} />
      <ul className="divide-y divide-slate-100">
        {c.pageItems.map((i) => (
          <li key={i.id} className="flex items-center gap-3 px-5 py-3 text-sm">
            <Badge tone="indigo">{ko.marketTypes[i.type] ?? i.type}</Badge>
            <Link to={`/market/${i.item_key}`} className="font-medium hover:underline">
              {i.item_name}
            </Link>
            <span className="text-xs text-slate-400">v{i.version}</span>
            <StatusBadge status={i.status} />
            {updates.get(i.id)?.update_available && (
              <Badge tone="amber">새 버전 v{updates.get(i.id)?.latest_version}</Badge>
            )}
            <span className="ml-auto text-xs text-slate-400">{formatDate(i.installed_at)}</span>
            {canManage(role) && updates.get(i.id)?.update_available && (
              <Button
                size="sm"
                variant="outline"
                disabled={update.isPending}
                onClick={() =>
                  update.mutate(i.id, {
                    onSuccess: (r) => toast.success(`v${r.version}(으)로 업데이트했어요.`),
                    onError: (err) => toast.error(err),
                  })
                }
              >
                업데이트
              </Button>
            )}
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
      <ListPager c={c} className="border-t border-slate-100 px-5 py-2.5" />
    </Card>
  );
}

/** 분류 칩: 분류마다 개수를 보여 주고 누르면 그 분류만 본다(다시 누르면 해제). */
function CategoryChips({
  items,
  value,
  onChange,
}: {
  items?: { category?: string }[];
  value: string;
  onChange: (v: string) => void;
}) {
  const counts = new Map<string, number>();
  for (const it of items ?? []) {
    if (it.category) counts.set(it.category, (counts.get(it.category) ?? 0) + 1);
  }
  if (counts.size < 2) return null;
  const cats = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "ko"));
  return (
    <div className="-mx-1 mb-3 flex gap-1.5 overflow-x-auto px-1 pb-1" aria-label="분류">
      {cats.map(([cat, n]) => (
        <button
          key={cat}
          type="button"
          aria-pressed={value === cat}
          onClick={() => onChange(value === cat ? "" : cat)}
          className={cn(
            "shrink-0 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors",
            value === cat
              ? "border-indigo-300 bg-indigo-50 text-indigo-700"
              : "border-slate-200 bg-white text-slate-600 hover:border-slate-300",
          )}
        >
          {cat} <span className="text-slate-400">{n}</span>
        </button>
      ))}
    </div>
  );
}

export default function MarketPage() {
  const ws = useSession((s) => s.workspaceId);
  const [params, setParams] = useSearchParams();
  const type = params.get("type") ?? "";
  const [tab, setTab] = useState<"all" | "installed">("all");
  const items = useMarketItems(ws, { type: type || undefined });
  // 종류별 개수는 전체 목록에서 센다(종류 칩에 표시)
  const all = useMarketItems(ws, {});
  const [sort, setSort] = useState<SortKey>("popular");
  const sorted = useMemo(() => sortItems(items.data, sort), [items.data, sort]);
  const c = useListControls(sorted, {
    key: "market-items",
    defaultSize: 20,
    search: (it) => `${it.name} ${it.summary} ${it.publisher} ${it.tags.join(" ")}`,
    filters: [
      {
        id: "category",
        label: "분류",
        options: optionsFrom(items.data, (it) => it.category),
        match: (it, v) => it.category === v,
      },
      {
        id: "installed",
        label: "설치",
        options: [
          { value: "yes", label: "설치됨" },
          { value: "no", label: "설치 안 함" },
        ],
        match: (it, v) => Boolean(it.installed) === (v === "yes"),
      },
      {
        id: "price",
        label: "가격",
        options: [
          { value: "free", label: "무료" },
          { value: "paid", label: "유료" },
        ],
        match: (it, v) => it.price > 0 === (v === "paid"),
      },
    ],
  });

  return (
    <PageContainer>
      <PageHeader
        title="마켓"
        description="필요한 서비스 연결·단계·템플릿을 설치해서 바로 써요."
        help={<HelpButton page="market" />}
      />
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
              { key: "", label: "전체", count: all.data?.length },
              ...(Object.keys(ko.marketTypes) as MarketType[]).map((t) => ({
                key: t,
                label: ko.marketTypes[t],
                count: all.data?.filter((it) => it.type === t).length,
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
                {c.count !== undefined && (
                  <span
                    className={cn(
                      "ml-1 text-xs",
                      type === c.key ? "text-white/70" : "text-slate-400",
                    )}
                  >
                    {c.count}
                  </span>
                )}
              </button>
            ))}
          </div>
          <CategoryChips
            items={items.data}
            value={c.filterValues.category ?? ""}
            onChange={(v) => c.setFilter("category", v)}
          />
          {(items.data ?? []).length > 0 && (
            <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start">
              <ListToolbar c={c} placeholder="이름·설명·태그로 찾기" className="flex-1" />
              <label className="flex shrink-0 items-center gap-2 text-xs text-slate-500">
                정렬
                <select
                  aria-label="정렬"
                  value={sort}
                  onChange={(e) => setSort(e.target.value as SortKey)}
                  className="h-9 rounded-lg border border-slate-200 bg-white px-2 text-sm text-slate-700"
                >
                  {SORTS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
          {items.isLoading && <Loading />}
          <ErrorBox error={items.error} />
          {items.data?.length === 0 && <Empty>조건에 맞는 아이템이 없어요.</Empty>}
          <NoMatch c={c} />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {c.pageItems.map((it) => (
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
          {(items.data ?? []).length > 0 && <ListPager c={c} className="mt-3" />}
        </>
      )}
    </PageContainer>
  );
}
