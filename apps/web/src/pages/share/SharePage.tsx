import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useLoggedIn } from "@/app/useAuthState";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ko } from "@/i18n/ko";
import { errorLines } from "@/lib/api/client";
import { sendPublicChat, usePublicApp } from "@/lib/api/resources";
import { cn } from "@/lib/cn";

interface ChatLine {
  role: "user" | "assistant" | "error";
  text: string;
  hint?: string;
}

/** 배포된 앱을 쓰는 화면. 위젯(iframe)은 ?embed=1 로 연다. */
export default function SharePage() {
  const { token = "" } = useParams();
  const [params] = useSearchParams();
  const embed = params.get("embed") === "1";
  const loggedIn = useLoggedIn();
  const app = usePublicApp(token);
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [message, setMessage] = useState("");
  const [extra, setExtra] = useState<Record<string, string>>({});
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const sessionRef = useRef<string | undefined>(undefined);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ block: "end" });
  }, [lines, status]);

  if (app.isLoading) return <Loading />;
  if (app.error)
    return (
      <div className="mx-auto max-w-md p-6">
        <ErrorBox error={app.error} />
      </div>
    );
  const info = app.data;
  if (!info) return null;

  const extraFields = info.input_fields.filter((f) => f.key !== "message");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const text = message.trim();
    if (!text || busy) return;
    setMessage("");
    setBusy(true);
    setLines((l) => [...l, { role: "user", text }]);
    try {
      await sendPublicChat(
        token,
        {
          message: text,
          session_id: sessionRef.current,
          input: extraFields.length ? { ...extra, message: text } : undefined,
        },
        (ev) => {
          const d = (ev.data ?? {}) as Record<string, unknown>;
          if (ev.event === "session") sessionRef.current = String(d.session_id);
          else if (ev.event === "status") setStatus(String(d.message ?? ""));
          else if (ev.event === "answer")
            setLines((l) => [...l, { role: "assistant", text: String(d.text ?? "") }]);
          else if (ev.event === "error")
            setLines((l) => [
              ...l,
              {
                role: "error",
                text: String(d.message ?? "문제가 생겼어요."),
                hint: d.hint as string | undefined,
              },
            ]);
          else if (ev.event === "done" && d.session_id) sessionRef.current = String(d.session_id);
        },
      );
    } catch (err) {
      const { message: m, hint } = errorLines(err);
      setLines((l) => [...l, { role: "error", text: m, hint }]);
    } finally {
      setBusy(false);
      setStatus("");
    }
  };

  const blocked = !info.can_use;

  return (
    <div className={cn("flex flex-col bg-slate-50", embed ? "h-screen" : "min-h-screen")}>
      <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3">
        <span className="text-2xl" aria-hidden>
          {info.icon || "🤖"}
        </span>
        <div className="min-w-0">
          <p className="truncate font-semibold">{info.name}</p>
          {!embed && info.description && (
            <p className="truncate text-xs text-slate-500">{info.description}</p>
          )}
        </div>
        {!embed && (
          <span className="ml-auto text-xs text-slate-400">{ko.appName}로 만들었어요</span>
        )}
      </header>
      {blocked ? (
        <div className="mx-auto max-w-md p-6 text-sm">
          <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3">
            <p className="font-medium text-amber-900">
              {info.requires_login && !loggedIn
                ? "로그인이 필요한 앱이에요."
                : "이 앱을 쓸 권한이 없어요."}
            </p>
            <p className="text-amber-800">
              {info.requires_login && !loggedIn
                ? "워크스페이스 계정으로 로그인한 뒤 다시 열어 주세요."
                : "앱을 배포한 사람에게 사용 권한을 요청하세요."}
            </p>
          </div>
          {info.requires_login && !loggedIn && (
            <Link
              to={`/login?next=${encodeURIComponent(`/share/${token}${embed ? "?embed=1" : ""}`)}`}
              target={embed ? "_blank" : undefined}
              className="mt-3 inline-block text-indigo-600"
            >
              로그인하러 가기
            </Link>
          )}
        </div>
      ) : (
        <>
          <div
            className={cn(
              "flex-1 space-y-3 overflow-y-auto px-4 py-4",
              !embed && "mx-auto w-full max-w-2xl",
            )}
          >
            {lines.length === 0 && (
              <p className="text-center text-sm text-slate-500">무엇이든 물어보세요.</p>
            )}
            {lines.map((l, i) => (
              <div
                key={i}
                className={cn("flex", l.role === "user" ? "justify-end" : "justify-start")}
              >
                <div
                  className={cn(
                    "max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm",
                    l.role === "user" && "bg-indigo-600 text-white",
                    l.role === "assistant" && "border border-slate-200 bg-white text-slate-900",
                    l.role === "error" && "border border-red-200 bg-red-50 text-red-900",
                  )}
                >
                  {l.text}
                  {l.hint && <p className="mt-0.5 text-xs text-red-700">{l.hint}</p>}
                </div>
              </div>
            ))}
            {status && <p className="text-xs text-slate-400">{status}</p>}
            <div ref={bottomRef} />
          </div>
          <form
            onSubmit={(e) => void submit(e)}
            className={cn("border-t border-slate-200 bg-white p-3", !embed && "sticky bottom-0")}
          >
            <div className={cn("space-y-2", !embed && "mx-auto max-w-2xl")}>
              {extraFields.map((f) => (
                <Input
                  key={f.key}
                  aria-label={f.label || f.key}
                  placeholder={f.label || f.key}
                  value={extra[f.key] ?? ""}
                  onChange={(e) => setExtra({ ...extra, [f.key]: e.target.value })}
                />
              ))}
              <div className="flex gap-2">
                <Input
                  aria-label="메시지"
                  placeholder="메시지를 입력하세요"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                />
                <Button type="submit" disabled={busy || !message.trim()}>
                  보내기
                </Button>
              </div>
            </div>
          </form>
        </>
      )}
    </div>
  );
}
