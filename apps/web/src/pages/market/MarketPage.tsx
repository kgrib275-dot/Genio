import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, Empty, PageHeader } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { Tabs } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toast-store";
import { ko } from "@/i18n/ko";
import { useInstallations, useMarketItems, useUninstall } from "@/lib/api/resources";
import type { MarketType } from "@/lib/api/types";
import { formatDate } from "@/lib/cn";
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
          <div className="mb-4 flex flex-wrap gap-2">
            <Select
              aria-label="종류"
              className="w-44"
              value={type}
              onChange={(e) => {
                const next = new URLSearchParams(params);
                if (e.target.value) next.set("type", e.target.value);
                else next.delete("type");
                setParams(next);
              }}
            >
              <option value="">모든 종류</option>
              {(Object.keys(ko.marketTypes) as MarketType[]).map((t) => (
                <option key={t} value={t}>
                  {ko.marketTypes[t]}
                </option>
              ))}
            </Select>
            <Input
              aria-label="검색"
              className="max-w-xs"
              placeholder="이름·설명 검색"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          {items.isLoading && <Loading />}
          <ErrorBox error={items.error} />
          {items.data?.length === 0 && <Empty>조건에 맞는 아이템이 없어요.</Empty>}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {(items.data ?? []).map((it) => (
              <Link key={it.key} to={`/market/${it.key}`}>
                <Card className="h-full p-4 transition-shadow hover:shadow-md">
                  <div className="flex items-center gap-2">
                    <Badge tone="indigo">{ko.marketTypes[it.type] ?? it.type}</Badge>
                    {it.installed && <Badge tone="green">설치됨</Badge>}
                    <span className="ml-auto text-xs text-slate-500">
                      {it.price > 0 ? `${it.price.toLocaleString()}원` : "무료"}
                    </span>
                  </div>
                  <p className="mt-2 font-semibold">{it.name}</p>
                  <p className="mt-1 line-clamp-2 text-sm text-slate-600">{it.summary}</p>
                  <p className="mt-2 text-xs text-slate-400">
                    {it.publisher} · v{it.version} · 설치 {it.installs}
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
