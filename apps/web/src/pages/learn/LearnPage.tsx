// 배우기: 샘플을 열어 따라 하며 익히는 강좌 8개 + Dify·n8n 대응표
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock,
  ExternalLink,
  GraduationCap,
  KeyRound,
  PackagePlus,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import { toast } from "@/components/ui/toast-store";
import { HelpButton } from "@/help/HelpButton";
import { LESSONS, TERMS, type Lesson } from "@/help/learn";
import {
  readDone,
  useInstallSamples,
  useSampleStatus,
  writeDone,
  type SampleStatus,
} from "@/lib/api/learn";
import { cn } from "@/lib/cn";
import { canEdit, useSession } from "@/store/session";

/** **굵게**만 지원하는 짧은 글 */
function Rich({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("**") && p.endsWith("**") ? (
          <b key={i} className="font-semibold text-slate-900">
            {p.slice(2, -2)}
          </b>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

function SampleLinks({ lesson, status }: { lesson: Lesson; status?: SampleStatus }) {
  if (!lesson.samples.length) return null;
  const apps = status?.apps ?? [];
  return (
    <div className="flex flex-wrap gap-2">
      {lesson.samples.map((no) => {
        const a = apps.find((x) => x.name.startsWith(no));
        return a ? (
          <Link
            key={no}
            to={`/apps/${a.id}/builder`}
            className="inline-flex items-center gap-1 rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-100"
          >
            <ExternalLink className="h-3.5 w-3.5" /> {a.name} 열기
          </Link>
        ) : (
          <span
            key={no}
            className="inline-flex items-center rounded-lg border border-dashed border-slate-300 px-2.5 py-1.5 text-xs text-slate-400"
          >
            샘플 {no} (먼저 샘플을 넣어 주세요)
          </span>
        );
      })}
    </div>
  );
}

function LessonCard({
  lesson,
  done,
  onToggleDone,
  status,
  open,
  onToggle,
}: {
  lesson: Lesson;
  done: boolean;
  onToggleDone: () => void;
  status?: SampleStatus;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <Card className={cn("overflow-hidden", done && "opacity-80")}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-4 py-3.5 text-left hover:bg-slate-50 sm:px-5"
      >
        {done ? (
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" />
        ) : (
          <Circle className="mt-0.5 h-5 w-5 shrink-0 text-slate-300" />
        )}
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-slate-900">{lesson.title}</p>
          <p className="mt-0.5 text-sm text-slate-500">{lesson.goal}</p>
          <div className="mt-1.5 flex flex-wrap gap-2 text-[11px] text-slate-500">
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" /> 약 {lesson.minutes}분
            </span>
            {lesson.samples.length > 0 && <span>샘플 {lesson.samples.join(" ")}</span>}
            {lesson.needsAiKey && (
              <span className="inline-flex items-center gap-1 text-amber-700">
                <KeyRound className="h-3 w-3" /> AI 키 필요
              </span>
            )}
          </div>
        </div>
        {open ? (
          <ChevronDown className="mt-1 h-4 w-4 shrink-0 text-slate-400" />
        ) : (
          <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-slate-400" />
        )}
      </button>
      {open && (
        <div className="space-y-4 border-t border-slate-100 px-4 py-4 text-sm sm:px-5">
          <SampleLinks lesson={lesson} status={status} />
          <ol className="space-y-2">
            {lesson.steps.map((s, i) => (
              <li key={i} className="flex gap-2.5">
                <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-[11px] font-bold text-indigo-700">
                  {i + 1}
                </span>
                <span className="leading-relaxed text-slate-700">
                  <Rich text={s} />
                </span>
              </li>
            ))}
          </ol>
          <div className="rounded-lg bg-emerald-50 px-3 py-2.5">
            <p className="mb-1 text-xs font-semibold text-emerald-800">잘 됐는지 확인</p>
            <ul className="list-disc space-y-0.5 pl-4 text-emerald-900">
              {lesson.check.map((c, i) => (
                <li key={i}>
                  <Rich text={c} />
                </li>
              ))}
            </ul>
          </div>
          {lesson.compare && (
            <p className="rounded-lg bg-slate-50 px-3 py-2.5 text-xs text-slate-600">
              <b className="text-slate-700">Dify·n8n을 써 봤다면</b> — {lesson.compare}
            </p>
          )}
          <Button size="sm" variant={done ? "outline" : "primary"} onClick={onToggleDone}>
            <CheckCircle2 className="h-3.5 w-3.5" /> {done ? "다시 볼게요" : "다 해 봤어요"}
          </Button>
        </div>
      )}
    </Card>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-base font-bold text-slate-900">{title}</h2>
      {children}
    </section>
  );
}

export default function LearnPage() {
  const { workspaceId: ws, role } = useSession();
  const status = useSampleStatus(ws);
  const install = useInstallSamples(ws);
  const [done, setDone] = useState<string[]>(readDone);
  const [open, setOpen] = useState<string | null>(LESSONS[0]?.id ?? null);

  const toggleDone = (id: string) =>
    setDone((d) => {
      const next = d.includes(id) ? d.filter((x) => x !== id) : [...d, id];
      writeDone(next);
      return next;
    });

  const installed = status.data?.installed;
  return (
    <PageContainer>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <GraduationCap className="h-6 w-6 text-indigo-500" /> 배우기
          </span>
        }
        description="샘플을 열어 따라 하며 챗봇과 흐름을 만드는 법을 익혀요. 순서대로 하면 1시간 안에 다 볼 수 있어요."
        help={<HelpButton page="learn" />}
      />
      <div className="space-y-8">
        <Card className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:p-5">
          <PackagePlus className="h-8 w-8 shrink-0 text-amber-500" />
          <div className="min-w-0 flex-1 text-sm">
            <p className="font-semibold text-slate-900">
              {installed ? "샘플 10가지가 들어 있어요" : "먼저 샘플 10가지를 넣어 주세요"}
            </p>
            <p className="text-slate-500">
              {installed
                ? "왼쪽 메뉴 프로젝트 > '샘플 체험'에 있어요. 마음껏 고쳐 보고, 망가지면 새 워크스페이스에 다시 넣으면 돼요."
                : "앱 10개(7개는 AI 키 없이 동작), 데이터 표 3개, 사내 규정 지식베이스가 '샘플 체험' 프로젝트로 들어가요."}
            </p>
            <p className="mt-1 text-xs text-slate-400">
              진도 {done.length}/{LESSONS.length}
            </p>
          </div>
          {!installed && canEdit(role) && (
            <Button
              onClick={() =>
                install.mutate(undefined, {
                  onSuccess: () =>
                    toast.success("샘플을 넣었어요. 강좌의 '열기' 버튼으로 바로 열어 보세요."),
                })
              }
              disabled={install.isPending || status.isLoading}
            >
              <PackagePlus className="h-4 w-4" /> {install.isPending ? "넣는 중…" : "샘플 넣기"}
            </Button>
          )}
        </Card>
        <ErrorBox error={install.error ?? status.error} />

        <Section title="따라 하기 강좌">
          <div className="space-y-3">
            {LESSONS.map((l) => (
              <LessonCard
                key={l.id}
                lesson={l}
                done={done.includes(l.id)}
                onToggleDone={() => toggleDone(l.id)}
                status={status.data}
                open={open === l.id}
                onToggle={() => setOpen((o) => (o === l.id ? null : l.id))}
              />
            ))}
          </div>
        </Section>

        <Section title="Dify·n8n을 써 봤다면: 이름 대응표">
          <Card className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-medium">하는 일</th>
                  <th className="px-4 py-2 font-medium">Dify</th>
                  <th className="px-4 py-2 font-medium">n8n</th>
                  <th className="px-4 py-2 font-medium text-indigo-700">제니오</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {TERMS.map((t) => (
                  <tr key={t.concept}>
                    <td className="px-4 py-2 font-medium text-slate-700">{t.concept}</td>
                    <td className="px-4 py-2 text-slate-500">{t.dify}</td>
                    <td className="px-4 py-2 text-slate-500">{t.n8n}</td>
                    <td className="px-4 py-2 font-medium text-indigo-700">{t.genio}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </Section>
      </div>
    </PageContainer>
  );
}
