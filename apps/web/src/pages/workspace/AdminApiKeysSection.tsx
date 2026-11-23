// sections.tsx에서 분리한 구간: AdminApiKeysSection
import { KeyRound, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { toast } from "@/components/ui/toast-store";
import { useAdminApiKeys, useDeleteApiKey } from "@/lib/api/v2";
import { formatDate } from "@/lib/cn";
import { optionsFrom, useListControls } from "@/lib/useListControls";

// ---------------- 전체 API 키 ----------------
export function AdminApiKeysSection({ ws }: { ws: string }) {
  const keys = useAdminApiKeys(ws);
  const del = useDeleteApiKey();
  const kc = useListControls(keys.data, {
    key: "admin-api-keys",
    search: (k) => `${k.name} ${k.prefix} ${k.app_name ?? ""}`,
    filters: [
      {
        id: "app",
        label: "앱",
        options: optionsFrom(keys.data, (k) => k.app_name ?? null),
        match: (k, v) => k.app_name === v,
      },
      {
        id: "used",
        label: "사용",
        options: [
          { value: "used", label: "쓴 적 있음" },
          { value: "never", label: "한 번도 안 씀" },
        ],
        match: (k, v) => (v === "used") === Boolean(k.last_used_at),
      },
    ],
  });
  if (keys.isLoading) return <Loading />;
  if (keys.error) return <ErrorBox error={keys.error} />;
  if (!keys.data?.length)
    return (
      <EmptyState
        icon={<KeyRound className="h-5 w-5" />}
        title="아직 만든 API 키가 없어요"
        description="다른 시스템에서 앱을 부르려면 앱을 열고 '외부 연동' 탭에서 키를 만들어요. 만든 키는 여기서 한눈에 관리해요."
        action={{ label: "앱 고르러 가기", to: "/" }}
      />
    );
  return (
    <div className="space-y-3">
      <ListToolbar c={kc} placeholder="키 이름·앱 검색" />
      <Card className="overflow-hidden">
        <ul className="divide-y divide-slate-100">
          {kc.pageItems.map((k) => (
            <li key={k.id} className="flex flex-wrap items-center gap-2 px-4 py-3 text-sm">
              <KeyRound className="h-4 w-4 text-slate-400" />
              <span className="font-medium">{k.name}</span>
              <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{k.prefix}…</code>
              {k.app_id && (
                <Link
                  to={`/apps/${k.app_id}/api`}
                  className="text-xs text-indigo-600 hover:underline"
                >
                  {k.app_name ?? "앱"}
                </Link>
              )}
              <span className="basis-full text-xs text-slate-400 sm:basis-auto">
                만든 날 {formatDate(k.created_at)} · 마지막 사용{" "}
                {k.last_used_at ? formatDate(k.last_used_at) : "없음"}
              </span>
              <Button
                size="sm"
                variant="ghost"
                className="ml-auto text-red-600"
                aria-label={`${k.name} 키 지우기`}
                onClick={() => {
                  if (window.confirm(`'${k.name}' 키를 지울까요?`))
                    del.mutate(k.id, { onError: (err) => toast.error(err) });
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </li>
          ))}
        </ul>
        <NoMatch c={kc} />
      </Card>
      <ListPager c={kc} />
    </div>
  );
}
