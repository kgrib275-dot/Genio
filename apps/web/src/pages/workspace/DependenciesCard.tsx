// 후속(O3): 연결 관계 지도 — 바꾸거나 지우기 전에 '이걸 쓰는 앱'을 본다
import { useState } from "react";
import { Link } from "react-router-dom";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { useDependencies } from "@/lib/api/dependencies";
import { cn } from "@/lib/cn";

export function DependenciesCard({ ws }: { ws: string }) {
  const q = useDependencies(ws);
  const [kind, setKind] = useState("");
  const d = q.data;
  const kinds = [...new Map((d?.resources ?? []).map((r) => [r.kind, r.kind_label])).entries()];
  const rows = (d?.resources ?? []).filter((r) => !kind || r.kind === kind);
  return (
    <Card>
      <CardHeader
        title="연결 관계"
        description="연결 정보·지식베이스·데이터 표·스킬·다른 앱을 어떤 앱이 쓰는지 보여 줘요. 바꾸거나 지우기 전에 확인하세요. 앱의 작업본 기준이에요."
      />
      <CardBody className="space-y-3">
        {q.isLoading && <Loading />}
        <ErrorBox error={q.error} />
        {d && (d.missing_count > 0 || d.unused_count > 0) && (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
            {d.missing_count > 0 && `없어진 자원을 가리키는 설정이 ${d.missing_count}곳 있어요. `}
            {d.unused_count > 0 && `아무 앱도 쓰지 않는 자원이 ${d.unused_count}개 있어요.`}
          </p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {[["", "전체"], ...kinds].map(([k, label]) => (
            <button
              key={k}
              type="button"
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-xs",
                kind === k
                  ? "border-indigo-300 bg-indigo-50 text-indigo-700"
                  : "border-slate-200 text-slate-600",
              )}
              onClick={() => setKind(k as string)}
            >
              {label}
            </button>
          ))}
        </div>
        {d && rows.length === 0 && <p className="text-sm text-slate-500">보여 줄 자원이 없어요.</p>}
        <ul className="divide-y divide-slate-100 text-sm" data-testid="dep-list">
          {rows.map((r) => (
            <li key={`${r.kind}:${r.id}`} className="py-2">
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400">{r.kind_label}</span>
                <span className="font-medium">{r.name}</span>
                {r.unused && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                    안 쓰는 중
                  </span>
                )}
              </div>
              {r.used_by.length > 0 && (
                <p className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-slate-500">
                  쓰는 앱:
                  {r.used_by.map((u) => (
                    <Link
                      key={u.app_id}
                      to={`/apps/${u.app_id}/builder`}
                      className="text-indigo-600 hover:underline"
                    >
                      {u.app_name}
                    </Link>
                  ))}
                </p>
              )}
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
