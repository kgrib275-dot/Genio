// 전체 검색창(Ctrl/⌘ + K): 앱·프로젝트·지식베이스·데이터 표·연결 정보·마켓·화면을 한 곳에서 찾아 간다.
// 결과는 서버가 이 사용자의 역할에 맞게 걸러 준다. 방향키로 고르고 Enter로 열고 Esc로 닫는다.
import {
  BookOpen,
  Bot,
  Compass,
  FolderKanban,
  History,
  Keyboard,
  LifeBuoy,
  Plug,
  Search,
  Sparkles,
  Store,
  Table2,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ErrorBox } from "@/components/ErrorBox";
import { usePaletteSearch, type PaletteGroup } from "@/lib/api/search";
import { cn } from "@/lib/cn";
import { openHelp, openShortcuts, startTour } from "@/lib/helpEvents";
import { flatten, highlight, moveIndex, pushRecent, readRecents, type Row } from "@/lib/palette";
import { IS_MAC } from "@/lib/shortcuts";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { norm } from "@/lib/useListControls";
import { useSession } from "@/store/session";

const KIND_ICON: Record<string, LucideIcon> = {
  pages: Compass,
  apps: Bot,
  projects: FolderKanban,
  knowledge: BookOpen,
  tables: Table2,
  connections: Plug,
  market: Store,
  recent: History,
  actions: Sparkles,
};

/** 화면 이동이 아니라 바로 하는 일(검색어와 맞을 때만 보인다) */
const ACTIONS: (Row & { words: string })[] = [
  {
    id: "shortcuts",
    title: "단축키 보기",
    subtitle: "Shift + ?",
    to: "action:shortcuts",
    kind: "actions",
    label: "바로 하기",
    words: "단축키 키보드 shortcut keys",
  },
  {
    id: "tour",
    title: "화면 안내 다시 보기",
    subtitle: "처음 쓰는 사람을 위한 화면 투어",
    to: "action:tour",
    kind: "actions",
    label: "바로 하기",
    words: "투어 안내 처음 tour",
  },
  {
    id: "help",
    title: "도움·문의",
    subtitle: "사용설명서 찾기, 의견 보내기",
    to: "action:help",
    kind: "actions",
    label: "바로 하기",
    words: "도움말 문의 의견 질문 help",
  },
];

function runAction(to: string): void {
  if (to === "action:shortcuts") openShortcuts();
  else if (to === "action:tour") startTour();
  else if (to === "action:help") openHelp();
}

function Marked({ text, query }: { text: string; query: string }): ReactNode {
  return highlight(text, query).map((s, i) =>
    s.hit ? (
      <mark key={i} className="rounded bg-indigo-100 px-0.5 text-indigo-800">
        {s.text}
      </mark>
    ) : (
      <span key={i}>{s.text}</span>
    ),
  );
}

/** 열 때마다 새로 만들어서(검색어·고른 줄·최근 항목이 처음 상태) 닫혀 있는 동안은 아무것도 그리지 않는다. */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  return open ? <PaletteBody onClose={onClose} /> : null;
}

function PaletteBody({ onClose }: { onClose: () => void }) {
  const ws = useSession((s) => s.workspaceId);
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [index, setIndex] = useState(0);
  const [recents] = useState<Row[]>(() => readRecents(ws));
  const boxRef = useRef<HTMLDivElement>(null);
  useFocusTrap(boxRef, true);

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(q.trim()), 150);
    return () => window.clearTimeout(t);
  }, [q]);

  const res = usePaletteSearch(ws, debounced, true);

  const groups: PaletteGroup[] = useMemo(() => {
    const out: PaletteGroup[] = [];
    if (debounced === "" && recents.length)
      out.push({ kind: "recent", label: "최근 열어 본 것", items: recents });
    out.push(...(res.data?.groups ?? []));
    const nq = norm(debounced);
    const acts = ACTIONS.filter(
      (a) => !nq || norm(`${a.title} ${a.subtitle} ${a.words}`).includes(nq),
    );
    if (acts.length) out.push({ kind: "actions", label: "바로 하기", items: acts });
    return out;
  }, [debounced, recents, res.data]);

  const rows = useMemo(() => flatten(groups), [groups]);
  useEffect(() => setIndex(0), [debounced]);
  useEffect(() => {
    document.getElementById(`pal-opt-${index}`)?.scrollIntoView?.({ block: "nearest" });
  }, [index]);

  const choose = (row: Row | undefined) => {
    if (!row) return;
    onClose();
    if (row.to.startsWith("action:")) {
      runAction(row.to);
      return;
    }
    if (row.kind !== "recent") pushRecent(ws, row);
    navigate(row.to);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setIndex((i) => moveIndex(i, e.key === "ArrowDown" ? 1 : -1, rows.length));
    } else if (e.key === "Enter" && !e.nativeEvent.isComposing) {
      e.preventDefault();
      choose(rows[index]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
    }
  };

  const waiting = q.trim() !== debounced || (res.isFetching && !res.data);
  let pos = -1;
  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center bg-slate-900/40 p-3 pt-[10vh] sm:pt-[14vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-label="전체 검색"
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className="flex max-h-[75vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl"
      >
        <div className="flex items-center gap-2 border-b border-slate-100 px-4">
          <Search className="h-4 w-4 shrink-0 text-slate-400" aria-hidden />
          <input
            autoFocus
            role="combobox"
            aria-expanded="true"
            aria-controls="pal-list"
            aria-activedescendant={rows.length ? `pal-opt-${index}` : undefined}
            aria-label="찾을 것"
            autoComplete="off"
            spellCheck={false}
            placeholder="앱·지식베이스·화면 찾기…"
            className="h-12 w-full bg-transparent text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <kbd className="hidden shrink-0 rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[10px] text-slate-500 sm:inline">
            Esc
          </kbd>
        </div>
        <div
          id="pal-list"
          role="listbox"
          aria-label="검색 결과"
          className="min-h-0 flex-1 overflow-y-auto p-2"
        >
          {res.error && <ErrorBox error={res.error} />}
          {groups.map((g) => {
            const Icon = KIND_ICON[g.kind] ?? Compass;
            return (
              <div key={g.kind} role="group" aria-label={g.label} className="mb-1">
                <p className="flex items-center gap-1.5 px-2 pb-1 pt-2 text-[11px] font-semibold text-slate-400">
                  <Icon className="h-3 w-3" aria-hidden /> {g.label}
                </p>
                {g.items.map((it) => {
                  pos += 1;
                  const i = pos;
                  const active = i === index;
                  return (
                    <div
                      key={`${g.kind}:${it.id}`}
                      id={`pal-opt-${i}`}
                      role="option"
                      aria-selected={active}
                      onMouseMove={() => i !== index && setIndex(i)}
                      onClick={() => choose(rows[i])}
                      className={cn(
                        "flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2",
                        active ? "bg-indigo-50" : "hover:bg-slate-50",
                      )}
                    >
                      <span
                        aria-hidden
                        className={cn(
                          "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-base",
                          active ? "bg-white text-indigo-600" : "bg-slate-100 text-slate-500",
                        )}
                      >
                        {it.icon && it.icon !== "🤖" ? it.icon : <Icon className="h-4 w-4" />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-slate-900">
                          <Marked text={it.title} query={debounced} />
                        </span>
                        {it.subtitle && (
                          <span className="block truncate text-xs text-slate-500">
                            <Marked text={it.subtitle} query={debounced} />
                          </span>
                        )}
                      </span>
                      <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">
                        {(rows[i] ?? it) && (rows[i]?.label ?? g.label)}
                      </span>
                    </div>
                  );
                })}
              </div>
            );
          })}
          {rows.length === 0 && !waiting && (
            <div className="px-4 py-8 text-center text-sm text-slate-500">
              <p className="font-medium text-slate-700">“{debounced}”에 맞는 것이 없어요.</p>
              <p className="mt-1 text-xs">
                낱말을 줄이거나 다르게 써 보세요. 역할에 따라 보이지 않는 항목도 있어요.
              </p>
            </div>
          )}
          {rows.length === 0 && waiting && (
            <p className="px-4 py-8 text-center text-sm text-slate-400">찾는 중…</p>
          )}
        </div>
        <div className="hidden items-center gap-4 border-t border-slate-100 px-4 py-2 text-[11px] text-slate-500 sm:flex">
          <span className="inline-flex items-center gap-1">
            <Keyboard className="h-3 w-3" aria-hidden /> ↑↓ 고르기
          </span>
          <span>Enter 열기</span>
          <span>Esc 닫기</span>
          <span className="ml-auto inline-flex items-center gap-1">
            <LifeBuoy className="h-3 w-3" aria-hidden /> {IS_MAC ? "⌘" : "Ctrl"} + K 로 언제든
            열어요
          </span>
        </div>
      </div>
    </div>
  );
}
