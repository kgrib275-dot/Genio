// 새 서비스 찾기: 공식 MCP 레지스트리에서 검색해서 바로 연결 정보로 설치한다(ADR 0020)
import { ExternalLink, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import {
  fetchCatalog,
  useCatalogEnabled,
  useInstallCatalogItem,
  type CatalogItem,
  type CatalogPage,
} from "@/lib/api/catalog";

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function Row({ ws, item }: { ws: string; item: CatalogItem }) {
  const install = useInstallCatalogItem(ws);
  const [open, setOpen] = useState(false);
  const [token, setToken] = useState("");
  const remote = item.remotes[0];
  const needsToken = remote?.headers.some((h) => h.secret) ?? false;
  return (
    <li className="space-y-2 rounded-lg border border-slate-200 p-3">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">
            {item.title} <span className="text-xs font-normal text-slate-400">v{item.version}</span>
          </p>
          <p className="text-xs text-slate-500">{item.description || "설명이 없어요."}</p>
          <p className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
            <code>{item.name}</code>
            {item.repository && (
              <a
                href={item.repository}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-0.5 hover:underline"
              >
                출처 <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </p>
        </div>
        {install.isSuccess ? (
          <span className="text-xs font-medium text-emerald-700">연결했어요</span>
        ) : item.installable ? (
          <Button size="sm" variant="outline" onClick={() => setOpen((v) => !v)}>
            연결하기
          </Button>
        ) : (
          <span
            className="text-xs text-slate-400"
            title="내 컴퓨터에서 돌리는 서버이거나, 주소에 직접 채울 값이 있어 바로 연결할 수 없어요."
          >
            바로 연결 불가
          </span>
        )}
      </div>
      {open && !install.isSuccess && remote && (
        <form
          className="space-y-2 rounded-md bg-slate-50 p-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            install.mutate(
              { name: item.name, token: token || undefined },
              {
                onSuccess: () => {
                  setToken("");
                  toast.success(
                    "연결 정보로 저장했어요. 아래 연결 목록에서 '도구 보기'로 확인해 보세요.",
                  );
                },
              },
            );
          }}
        >
          <p className="text-xs text-slate-600">
            누구나 올릴 수 있는 목록이에요. <b>출처를 확인한 뒤</b> 연결하세요. 접속 주소는{" "}
            <code>{hostOf(remote.url)}</code> 이에요.
          </p>
          {needsToken && (
            <Input
              type="password"
              autoComplete="off"
              placeholder="접속 토큰(서비스에서 발급받은 값)"
              aria-label="접속 토큰"
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          )}
          <ErrorBox error={install.error} />
          <Button type="submit" size="sm" disabled={install.isPending || (needsToken && !token)}>
            {install.isPending ? "연결하는 중…" : "이 서비스 연결"}
          </Button>
        </form>
      )}
    </li>
  );
}

export function CatalogCard({ ws }: { ws: string }) {
  const enabled = useCatalogEnabled(ws);
  const [q, setQ] = useState("");
  const [page, setPage] = useState<CatalogPage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [last, setLast] = useState("");

  const run = async (query: string, cursor = "") => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetchCatalog(ws, query, cursor);
      setPage(cursor && page ? { ...res, items: [...page.items, ...res.items] } : res);
      setLast(query);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-1.5">
            <Search className="h-4 w-4 text-slate-400" /> 새 서비스 찾기
          </span>
        }
        description="공식 MCP 목록에서 최신 서비스를 찾아 바로 연결해요. 연결하면 흐름의 '외부 도구 호출' 단계에서 쓸 수 있어요."
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
                aria-label="서비스 검색"
                placeholder="예: slack, notion, github"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
              <Button type="submit" disabled={busy}>
                {busy ? "찾는 중…" : "찾기"}
              </Button>
            </form>
            <ErrorBox error={error} />
            {page && page.items.length === 0 && (
              <p className="text-sm text-slate-500">
                찾은 서비스가 없어요. 다른 말로 검색해 보세요.
              </p>
            )}
            {page && page.items.length > 0 && (
              <ul className="max-h-[28rem] space-y-2 overflow-y-auto">
                {page.items.map((it) => (
                  <Row key={it.name} ws={ws} item={it} />
                ))}
              </ul>
            )}
            {page?.next_cursor && (
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => void run(last, page.next_cursor)}
              >
                더 보기
              </Button>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
