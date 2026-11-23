// sections.tsx에서 분리한 구간: AuditSection
import { Download, History } from "lucide-react";
import { useState } from "react";
import { DataView } from "@/components/DataView";
import { summarizeAudit } from "@/lib/auditSummary";
import { keyLabel, valueLabel } from "@/lib/dataLabels";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { toast } from "@/components/ui/toast-store";
import { ko } from "@/i18n/ko";
import { type Role } from "@/lib/api/types";
import { useAuditLogs, useMembers } from "@/lib/api/workspace";
import { downloadAuditCsv } from "@/lib/api/ops";
import { optionsFrom, useListControls } from "@/lib/useListControls";
import type { AuditLog } from "@/lib/api/types";

// ---------------- 활동 기록 ----------------
/** 활동 이름을 쉬운 말로 */
const ACTION_LABELS: Record<string, string> = {
  "annotation.create": "모범 답변 추가",
  "annotation.delete": "모범 답변 삭제",
  "api_key.create": "API 키 만들기",
  "api_key.delete": "API 키 삭제",
  "app.create": "앱 만들기",
  "app.delete": "앱 삭제",
  "app.deploy": "앱 배포",
  "app.duplicate": "앱 복제",
  "app.env_vars": "앱 환경 값 변경",
  "app.features": "앱 기능 설정 변경",
  "app.import": "앱 가져오기",
  "app.undeploy": "배포 중지",
  "app.update": "앱 정보 변경",
  "app.version_restore": "버전 되돌리기",
  "app.version_save": "버전 저장",
  "auth.password_change": "비밀번호 변경",
  "auth.signup": "가입",
  "feedback.send": "의견·문의",
  "credential.create": "연결 정보 추가",
  "credential.delete": "연결 정보 삭제",
  "kb.create": "지식베이스 만들기",
  "kb.delete": "지식베이스 삭제",
  "kb.document_delete": "문서 삭제",
  "kb.document_upload": "문서 올리기",
  "kb.document_url": "웹 문서 가져오기",
  "kb.update": "지식베이스 설정 변경",
  "llm_provider.create": "AI 연결 추가",
  "llm_provider.delete": "AI 연결 삭제",
  "market.install": "마켓 설치",
  "market.uninstall": "마켓 제거",
  "member.account_create": "계정 만들기",
  "member.invite": "멤버 초대",
  "member.invite_revoke": "초대 취소",
  "member.join": "멤버 합류",
  "member.password_reset": "비밀번호 재설정",
  "member.remove": "멤버 내보내기",
  "member.role_change": "역할 변경",
  "project.create": "프로젝트 만들기",
  "project.delete": "프로젝트 삭제",
  "project.members": "프로젝트 구성원 변경",
  "project.update": "프로젝트 변경",
  "run.approve": "실행 승인 처리",
  "system.update": "시스템 설정 변경",
  "workspace.transfer_ownership": "소유권 넘기기",
  "workspace.security": "보안 설정 변경",
  "support.access": "서비스 지원 접속",
  "catalog.search": "외부 서비스 찾기",
  "catalog.install": "외부 서비스 연결",
  "catalog.import_n8n": "n8n 템플릿 가져오기",
  "admin.workspaces_view": "전체 회사 현황 열람",
  "workspace.export": "데이터 내려받기",
  "workspace.privacy": "개인정보 설정 변경",
  "template.save": "팀 템플릿 저장",
  "template.delete": "팀 템플릿 삭제",
  "workspace.update": "워크스페이스 설정 변경",
};

const AREA_LABELS: Record<string, string> = {
  app: "앱",
  annotation: "앱",
  api_key: "API 키",
  auth: "계정",
  credential: "연결 정보",
  feedback: "의견",
  kb: "지식베이스",
  llm_provider: "AI 모델",
  market: "마켓",
  member: "멤버",
  project: "프로젝트",
  run: "실행",
  system: "시스템",
  workspace: "워크스페이스",
};

const TARGET_LABELS: Record<string, string> = {
  app: "앱",
  membership: "멤버",
  invitation: "초대",
  kb: "지식베이스",
  knowledge_base: "지식베이스",
  document: "문서",
  project: "프로젝트",
  run: "실행",
  api_key: "API 키",
  credential: "연결 정보",
  llm_provider: "AI 연결",
  market_item: "마켓 아이템",
  workspace: "워크스페이스",
  system: "시스템",
  annotation: "모범 답변",
  user: "사용자",
};

const actionLabel = (a: string) => ACTION_LABELS[a] ?? a;
const areaOf = (a: string) => a.split(".")[0] ?? a;
const AREA_TONE: Record<string, string> = {
  app: "bg-indigo-50 text-indigo-700",
  annotation: "bg-indigo-50 text-indigo-700",
  feedback: "bg-amber-50 text-amber-800",
  member: "bg-violet-50 text-violet-700",
  auth: "bg-violet-50 text-violet-700",
  kb: "bg-emerald-50 text-emerald-700",
  project: "bg-sky-50 text-sky-700",
  api_key: "bg-amber-50 text-amber-700",
  credential: "bg-amber-50 text-amber-700",
  llm_provider: "bg-amber-50 text-amber-700",
  system: "bg-rose-50 text-rose-700",
  workspace: "bg-rose-50 text-rose-700",
};

function metaText(v: unknown, people?: Map<string, string>): string {
  if (v === null || v === undefined) return "없음";
  if (typeof v === "boolean") return v ? "예" : "아니오";
  if (typeof v === "string") return people?.get(v) ?? ko.roles[v as Role] ?? valueLabel(v);
  if (typeof v === "number") return v.toLocaleString();
  return "";
}

/** 세부 내용: 단순 값은 '이름: 값' 칩으로, 복잡하면 펼쳐 보는 목록으로 */
function AuditMeta({
  meta,
  people,
}: {
  meta: Record<string, unknown>;
  people: Map<string, string>;
}) {
  const [open, setOpen] = useState(false);
  const entries = Object.entries(meta ?? {});
  if (entries.length === 0) return <span className="text-slate-300">-</span>;
  const simple = entries.filter(([, v]) => metaText(v) !== "");
  const complex = entries.filter(([, v]) => metaText(v) === "");
  return (
    <div className="flex flex-wrap items-center gap-1">
      {simple.map(([k, v]) => (
        <span
          key={k}
          className="inline-flex max-w-full items-center gap-1 rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px]"
        >
          <span className="text-slate-500">{keyLabel(k)}</span>
          <span className="truncate font-medium text-slate-800">{metaText(v, people)}</span>
        </span>
      ))}
      {complex.length > 0 && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="text-[11px] font-medium text-indigo-600 hover:underline"
        >
          {open ? "접기" : `자세히 (${complex.length})`}
        </button>
      )}
      {open && <DataView value={Object.fromEntries(complex)} className="mt-1 w-full" />}
    </div>
  );
}

const PERIODS = [
  { value: "1", label: "오늘" },
  { value: "7", label: "최근 7일" },
  { value: "30", label: "최근 30일" },
];

function withinDays(iso: string, days: number): boolean {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - (days - 1));
  return new Date(iso).getTime() >= start.getTime();
}

export function AuditSection({ ws }: { ws: string }) {
  const logs = useAuditLogs(ws);
  const [exporting, setExporting] = useState(false);
  const members = useMembers(ws);
  // 기록 안의 사용자 id를 이름으로
  const people = new Map((members.data ?? []).map((m) => [m.user_id, `${m.name} (${m.email})`]));
  const lc = useListControls<AuditLog>(logs.data, {
    key: "audit",
    search: (l) =>
      `${actionLabel(l.action)} ${l.action} ${l.user_email ?? ""} ${l.target_type} ${l.target_id ?? ""} ${JSON.stringify(l.meta ?? {})}`,
    filters: [
      {
        id: "area",
        label: "종류",
        options: optionsFrom(
          logs.data,
          (l) => areaOf(l.action),
          (a) => AREA_LABELS[a] ?? a,
        ),
        match: (l, v) => areaOf(l.action) === v,
      },
      {
        id: "action",
        label: "한 일",
        options: optionsFrom(logs.data, (l) => l.action, actionLabel),
        match: (l, v) => l.action === v,
      },
      {
        id: "user",
        label: "사람",
        options: optionsFrom(logs.data, (l) => l.user_email ?? "(시스템)"),
        match: (l, v) => (l.user_email ?? "(시스템)") === v,
      },
      {
        id: "period",
        label: "기간",
        options: PERIODS,
        match: (l, v) => withinDays(l.created_at, Number(v)),
      },
    ],
  });
  if (logs.isLoading) return <Loading />;
  if (logs.error) return <ErrorBox error={logs.error} />;
  if (!logs.data?.length)
    return (
      <EmptyState
        icon={<History className="h-5 w-5" />}
        title="아직 활동 기록이 없어요"
        description="멤버 초대, 앱 배포, 설정 변경, 의견·문의처럼 누가 무엇을 했는지 여기에 쌓여요."
      />
    );
  const digest = summarizeAudit(logs.data, 7, (l) =>
    l.user_id ? (people.get(l.user_id)?.split(" (")[0] ?? l.user_email ?? "알 수 없음") : "시스템",
  );
  return (
    <div className="space-y-3">
      {digest.total > 0 && (
        <section
          aria-label="지난 7일 요약"
          className="rounded-xl border border-indigo-100 bg-indigo-50/50 px-4 py-3 text-sm text-slate-700"
        >
          <p className="font-semibold text-slate-900">지난 7일 요약 · 기록 {digest.total}건</p>
          <p className="mt-1">
            가장 많이 한 일:{" "}
            {digest.top.map((t) => `${actionLabel(t.action)} ${t.count}번`).join(", ")}
          </p>
          <p>활발한 사람: {digest.people.map((p) => `${p.name}(${p.count}건)`).join(", ")}</p>
          {digest.notable.length > 0 && (
            <p className="text-amber-800">
              눈여겨볼 변경:{" "}
              {digest.notable.map((t) => `${actionLabel(t.action)} ${t.count}번`).join(", ")}
            </p>
          )}
        </section>
      )}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <ListToolbar c={lc} placeholder="한 일·사람·내용 검색" className="flex-1" />
        <Button
          variant="outline"
          className="shrink-0"
          disabled={exporting}
          onClick={async () => {
            setExporting(true);
            try {
              await downloadAuditCsv(ws, {
                area: lc.filterValues.area,
                action: lc.filterValues.action,
                user: lc.filterValues.user,
                days: lc.filterValues.period,
                q: lc.query,
              });
              toast.success("지금 고른 조건의 활동 기록을 CSV로 받았어요(최대 5만 줄).");
            } catch (err) {
              toast.error(err);
            } finally {
              setExporting(false);
            }
          }}
        >
          <Download className="h-4 w-4" /> {exporting ? "만드는 중…" : "CSV로 받기"}
        </Button>
      </div>
      <Card className="overflow-hidden">
        <div className="hidden grid-cols-[9.5rem_11rem_10rem_minmax(0,1fr)] gap-3 bg-slate-50 px-4 py-2 text-xs font-medium text-slate-500 lg:grid">
          <span>때</span>
          <span>누가</span>
          <span>한 일</span>
          <span>대상 · 세부 내용</span>
        </div>
        <ul className="divide-y divide-slate-100">
          {lc.pageItems.map((l) => (
            <li
              key={l.id}
              className="grid gap-x-3 gap-y-1 px-4 py-2.5 text-sm lg:grid-cols-[9.5rem_11rem_10rem_minmax(0,1fr)] lg:items-start"
            >
              <span className="order-3 text-xs tabular-nums text-slate-500 lg:order-none lg:pt-0.5">
                {new Date(l.created_at).toLocaleString("ko-KR", {
                  month: "numeric",
                  day: "numeric",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
              <span className="order-2 truncate text-xs text-slate-600 lg:order-none lg:pt-0.5">
                {l.user_email ?? "시스템"}
              </span>
              <span className="order-1 lg:order-none">
                <span
                  className={`inline-flex rounded-md px-1.5 py-0.5 text-xs font-medium ${AREA_TONE[areaOf(l.action)] ?? "bg-slate-100 text-slate-700"}`}
                  title={l.action}
                >
                  {actionLabel(l.action)}
                </span>
              </span>
              <div className="order-4 min-w-0 space-y-1 lg:order-none">
                {(l.target_type || l.target_id) && (
                  <p className="text-xs text-slate-500">
                    {TARGET_LABELS[l.target_type] ?? l.target_type}
                    {l.target_id && (
                      <span className="ml-1 text-slate-400" title={l.target_id}>
                        {l.target_id.length > 24 ? `${l.target_id.slice(0, 8)}…` : l.target_id}
                      </span>
                    )}
                  </p>
                )}
                <AuditMeta meta={l.meta} people={people} />
              </div>
            </li>
          ))}
        </ul>
        <NoMatch c={lc} />
      </Card>
      <ListPager c={lc} />
    </div>
  );
}
