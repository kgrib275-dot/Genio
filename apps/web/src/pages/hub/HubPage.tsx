// 후속(C1): 챗 허브 — 만들기 권한이 없어도 우리 팀이 배포한 챗봇·흐름을 한곳에서 골라 쓴다
import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AppIcon } from "@/components/AppIcon";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { useHub } from "@/lib/api/hub";
import { useSession } from "@/store/session";

export default function HubPage() {
  const ws = useSession((s) => s.workspaceId);
  const q = useHub(ws);
  const [text, setText] = useState("");
  const shown = useMemo(() => {
    const t = text.trim().toLowerCase();
    return (q.data ?? []).filter(
      (a) => !t || `${a.name} ${a.description}`.toLowerCase().includes(t),
    );
  }, [q.data, text]);
  return (
    <div className="mx-auto w-full max-w-5xl space-y-4 px-4 py-6 sm:px-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">챗 허브</h1>
        <p className="text-sm text-slate-500">
          우리 팀이 배포한 챗봇과 흐름 중 내가 쓸 수 있는 것이에요. 골라서 바로 써 보세요.
        </p>
      </div>
      <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
        <Search className="h-4 w-4 text-slate-400" aria-hidden />
        <input
          className="min-w-0 flex-1 bg-transparent text-sm focus:outline-none"
          placeholder="이름·설명으로 찾기"
          aria-label="챗봇 찾기"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      {q.isLoading && <Loading />}
      <ErrorBox error={q.error} />
      {q.data && shown.length === 0 && (
        <p className="text-sm text-slate-500" data-testid="hub-empty">
          {q.data.length === 0
            ? "아직 쓸 수 있는 앱이 없어요. 앱을 만든 사람에게 배포를 요청해 보세요."
            : "찾는 앱이 없어요. 다른 말로 찾아보세요."}
        </p>
      )}
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {shown.map((a) => (
          <li key={a.app_id}>
            <Link
              to={`/share/${a.token}`}
              className="flex h-full items-start gap-3 rounded-xl border border-slate-200 bg-white p-3 transition-colors hover:border-indigo-300 hover:bg-indigo-50/40"
            >
              <AppIcon name={a.name} icon={a.icon} />
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold text-slate-900">
                  {a.name}
                </span>
                <span className="mt-0.5 line-clamp-2 block text-xs text-slate-500">
                  {a.description || (a.type === "chat" ? "챗봇" : "흐름 앱")}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
