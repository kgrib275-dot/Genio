// v0.6 '도움·문의': 어느 화면에서든 오른쪽 아래 버튼으로 사용설명서를 찾고 의견·문의를 보낸다.
// 다른 곳에서 window 'genio:open-help' 이벤트로 열 수 있다(오류 화면의 '문의하기' 등).
import {
  ArrowLeft,
  GraduationCap,
  Keyboard,
  LifeBuoy,
  MessageSquare,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Select, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import type { HelpSection } from "@/help/content";
import { HelpSectionView } from "@/help/HelpView";
import { useSendFeedback, type FeedbackKind } from "@/lib/api/onboarding";
import { cn } from "@/lib/cn";
import { openPalette, openShortcuts, searchHelp, startTour } from "@/lib/helpEvents";
import { useSession } from "@/store/session";

type Tab = "help" | "feedback";

const KINDS: { value: FeedbackKind; label: string }[] = [
  { value: "question", label: "궁금해요" },
  { value: "bug", label: "안 돼요(오류)" },
  { value: "idea", label: "이런 게 있으면 좋겠어요" },
  { value: "other", label: "그 밖에" },
];

export function HelpWidget({ hideButton = false }: { hideButton?: boolean }) {
  const ws = useSession((s) => s.workspaceId);
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("help");
  const [q, setQ] = useState("");
  const [shown, setShown] = useState<HelpSection | null>(null);
  const [kind, setKind] = useState<FeedbackKind>("question");
  const [message, setMessage] = useState("");
  const send = useSendFeedback(ws);
  const results = useMemo(() => searchHelp(q), [q]);

  useEffect(() => {
    const onOpen = (e: Event) => {
      const d = (e as CustomEvent<{ tab?: Tab; message?: string }>).detail ?? {};
      e.preventDefault();
      setOpen(true);
      setTab(d.tab ?? "help");
      if (d.message) {
        setKind("bug");
        setMessage(d.message);
      }
    };
    window.addEventListener("genio:open-help", onOpen);
    return () => window.removeEventListener("genio:open-help", onOpen);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const submit = () =>
    send.mutate(
      { kind, message: message.trim(), page: pathname },
      {
        onSuccess: () => {
          toast.success("보냈어요. 관리자가 활동 기록에서 확인해요.");
          setMessage("");
          setOpen(false);
        },
      },
    );

  return (
    <>
      {!hideButton && !open && (
        <button
          type="button"
          data-tour="help-widget"
          aria-label="도움·문의 열기"
          onClick={() => setOpen(true)}
          className="fixed bottom-4 right-4 z-30 inline-flex h-11 items-center gap-1.5 rounded-full bg-indigo-600 px-4 text-sm font-semibold text-white shadow-lift hover:bg-indigo-500 md:bottom-6 md:right-6"
        >
          <LifeBuoy className="h-4 w-4" /> 도움
        </button>
      )}
      {open && (
        <div
          role="dialog"
          aria-modal="false"
          aria-label="도움·문의"
          className="fixed inset-x-2 bottom-2 z-50 flex max-h-[80dvh] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl sm:inset-x-auto sm:bottom-6 sm:right-6 sm:w-[380px]"
        >
          <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
            <LifeBuoy className="h-4 w-4 text-indigo-500" />
            <p className="flex-1 font-semibold text-slate-900">도움·문의</p>
            <button
              type="button"
              aria-label="닫기"
              onClick={() => setOpen(false)}
              className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex gap-1 border-b border-slate-100 px-3 py-2" role="tablist">
            {(
              [
                ["help", "도움말 찾기", Search],
                ["feedback", "의견·문의 보내기", MessageSquare],
              ] as const
            ).map(([key, label, Icon]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={cn(
                  "inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg py-1.5 text-sm",
                  tab === key
                    ? "bg-indigo-50 font-semibold text-indigo-700"
                    : "text-slate-500 hover:bg-slate-100",
                )}
              >
                <Icon className="h-3.5 w-3.5" /> {label}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {tab === "help" &&
              (shown ? (
                <div className="space-y-3">
                  <button
                    type="button"
                    onClick={() => setShown(null)}
                    className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800"
                  >
                    <ArrowLeft className="h-3.5 w-3.5" /> 목록으로
                  </button>
                  <HelpSectionView section={shown} />
                  <Link
                    to={`/help#${shown.id}`}
                    onClick={() => setOpen(false)}
                    className="inline-block text-xs text-indigo-600 hover:underline"
                  >
                    사용설명서에서 크게 보기
                  </Link>
                </div>
              ) : (
                <div className="space-y-3">
                  <input
                    aria-label="도움말 찾기"
                    placeholder="궁금한 것(예: 배포, AI 키, 병렬)"
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                  />
                  {results.length === 0 ? (
                    <p className="text-sm text-slate-500">
                      맞는 설명을 찾지 못했어요. 다른 말로 찾거나 &apos;의견·문의 보내기&apos;로
                      물어보세요.
                    </p>
                  ) : (
                    <ul className="space-y-1">
                      {results.slice(0, 8).map((s) => (
                        <li key={s.id}>
                          <button
                            type="button"
                            onClick={() => setShown(s)}
                            className="w-full rounded-lg px-2.5 py-2 text-left hover:bg-slate-50"
                          >
                            <span className="block text-sm font-medium text-slate-800">
                              {s.title}
                            </span>
                            <span className="line-clamp-1 text-xs text-slate-500">{s.summary}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="grid grid-cols-2 gap-2 border-t border-slate-100 pt-3">
                    <Link
                      to="/learn"
                      onClick={() => setOpen(false)}
                      className="inline-flex items-center justify-center gap-1 rounded-lg border border-slate-200 px-2 py-2 text-xs text-slate-700 hover:bg-slate-50"
                    >
                      <GraduationCap className="h-3.5 w-3.5" /> 배우기
                    </Link>
                    <button
                      type="button"
                      onClick={() => {
                        setOpen(false);
                        startTour();
                      }}
                      className="inline-flex items-center justify-center gap-1 rounded-lg border border-slate-200 px-2 py-2 text-xs text-slate-700 hover:bg-slate-50"
                    >
                      <Sparkles className="h-3.5 w-3.5" /> 화면 안내 다시 보기
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setOpen(false);
                        openShortcuts();
                      }}
                      className="inline-flex items-center justify-center gap-1 rounded-lg border border-slate-200 px-2 py-2 text-xs text-slate-700 hover:bg-slate-50"
                    >
                      <Keyboard className="h-3.5 w-3.5" /> 단축키 보기
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setOpen(false);
                        openPalette();
                      }}
                      className="inline-flex items-center justify-center gap-1 rounded-lg border border-slate-200 px-2 py-2 text-xs text-slate-700 hover:bg-slate-50"
                    >
                      <Search className="h-3.5 w-3.5" /> 전체 검색
                    </button>
                  </div>
                </div>
              ))}
            {tab === "feedback" && (
              <div className="space-y-3">
                <p className="text-sm text-slate-600">
                  막힌 점, 오류, 바라는 기능을 적어 주세요. 워크스페이스 관리자가 확인해요.
                </p>
                <Select
                  aria-label="종류"
                  value={kind}
                  onChange={(e) => setKind(e.target.value as FeedbackKind)}
                >
                  {KINDS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </Select>
                <Textarea
                  aria-label="내용"
                  rows={5}
                  maxLength={3000}
                  placeholder="예: 배포 버튼을 눌렀는데 아무 일도 안 일어나요."
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                />
                <p className="text-xs text-slate-400">
                  지금 보고 있는 화면 주소({pathname})가 함께 가요.
                </p>
                <ErrorBox error={send.error} />
                <Button
                  className="w-full"
                  disabled={send.isPending || message.trim().length < 2}
                  onClick={submit}
                >
                  {send.isPending ? "보내는 중…" : "보내기"}
                </Button>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
