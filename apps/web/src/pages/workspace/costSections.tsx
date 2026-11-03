// v0.5 비용·모델 화면(기능 정의서 §6·S8): 모델 카탈로그, 사람별 비용, 모델 교체 예상 비용,
// 월 한도·알림·보관 기간(소유자·관리자)
import { useState } from "react";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { ListPager, ListToolbar, NoMatch } from "@/components/ListControls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Empty } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { useCredentials } from "@/lib/api/resources";
import {
  useCostEstimate,
  useLimits,
  useLlmCatalog,
  useUpdateLimits,
  useUsageByUser,
  type WorkspaceLimits,
} from "@/lib/api/v5b";
import { formatCost } from "@/lib/cn";
import { optionsFrom, useListControls } from "@/lib/useListControls";

const PROVIDER_LABEL: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  google: "Google",
  "openai-compatible": "호환 API",
  azure: "Azure",
};

function yesNo(v: boolean) {
  return v ? "예" : "-";
}

/** 모델 카탈로그: 컨텍스트·단가·기능 비교 */
export function ModelCatalogCard() {
  const cat = useLlmCatalog();
  const c = useListControls(cat.data, {
    key: "llm-catalog",
    defaultSize: 20,
    search: (m) => `${m.model} ${m.label} ${m.provider}`,
    filters: [
      {
        id: "provider",
        label: "공급자",
        options: optionsFrom(
          cat.data,
          (m) => m.provider,
          (v) => PROVIDER_LABEL[v] ?? v,
        ),
        match: (m, v) => m.provider === v,
      },
      {
        id: "kind",
        label: "용도",
        options: [
          { value: "chat", label: "대화·생성" },
          { value: "embedding", label: "임베딩(지식베이스)" },
        ],
        match: (m, v) => (v === "embedding") === m.embedding,
      },
    ],
  });
  return (
    <Card className="min-w-0">
      <CardHeader
        title="모델 목록"
        description="쓸 수 있는 모델의 기억 크기·가격(100만 토큰당 달러)·기능이에요. 가격은 참고값이에요."
      />
      <CardBody className="space-y-3 p-0 pb-3">
        {cat.isLoading && <Loading />}
        <ErrorBox error={cat.error} />
        <ListToolbar c={c} placeholder="모델 이름 찾기" className="px-4 sm:px-5" />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="px-4 py-2 text-left font-medium sm:px-5">모델</th>
                <th className="px-2 py-2 text-left font-medium">공급자</th>
                <th className="px-2 py-2 text-right font-medium">기억 크기</th>
                <th className="px-2 py-2 text-right font-medium">입력 $</th>
                <th className="px-2 py-2 text-right font-medium">출력 $</th>
                <th className="px-2 py-2 text-center font-medium">도구</th>
                <th className="px-2 py-2 text-center font-medium">이미지</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {c.pageItems.map((m) => (
                <tr key={`${m.provider}-${m.model}`}>
                  <td className="px-4 py-2 sm:px-5">
                    <p className="font-medium text-slate-800">{m.label}</p>
                    <p className="font-mono text-[11px] text-slate-500">{m.model}</p>
                  </td>
                  <td className="px-2 py-2">
                    <Badge tone={m.embedding ? "indigo" : "blue"}>
                      {PROVIDER_LABEL[m.provider] ?? m.provider}
                    </Badge>
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-slate-600">
                    {m.context_window >= 10_000
                      ? `${Math.round(m.context_window / 1000).toLocaleString()}K`
                      : m.context_window.toLocaleString()}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums">{m.input_price || "-"}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{m.output_price || "-"}</td>
                  <td className="px-2 py-2 text-center">
                    {m.embedding ? "임베딩" : yesNo(m.tools)}
                  </td>
                  <td className="px-2 py-2 text-center">{yesNo(m.vision)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <NoMatch c={c} />
        <ListPager c={c} className="px-4 sm:px-5" />
      </CardBody>
    </Card>
  );
}

/** 사람별 비용 */
export function UsageByUserList({ ws }: { ws: string }) {
  const u = useUsageByUser(ws);
  const c = useListControls(u.data?.by_user, {
    key: "usage-by-user",
    search: (x) => `${x.name} ${x.email ?? ""}`,
  });
  if (u.isLoading) return <Loading />;
  if (u.error) return <ErrorBox error={u.error} />;
  if (!u.data?.by_user.length) return <Empty>아직 사용 기록이 없어요.</Empty>;
  return (
    <div className="space-y-3">
      <ListToolbar c={c} placeholder="이름·이메일 검색" />
      <Card className="overflow-hidden">
        <div className="hidden grid-cols-[1fr_repeat(4,6rem)] gap-2 bg-slate-50 px-4 py-2 text-xs font-medium text-slate-500 md:grid">
          <span>사람</span>
          <span className="text-right">실행</span>
          <span className="text-right">입력 토큰</span>
          <span className="text-right">출력 토큰</span>
          <span className="text-right">비용</span>
        </div>
        <ul className="divide-y divide-slate-100">
          {c.pageItems.map((x) => (
            <li
              key={x.user_id ?? "anon"}
              className="grid grid-cols-2 gap-x-2 gap-y-0.5 px-4 py-2.5 text-sm md:grid-cols-[1fr_repeat(4,6rem)]"
            >
              <span className="col-span-2 min-w-0 md:col-span-1">
                <span className="font-medium">{x.name}</span>
                {x.email && <span className="ml-1 text-xs text-slate-500">{x.email}</span>}
              </span>
              <span className="text-xs text-slate-500 md:text-right md:text-sm md:text-slate-700">
                <span className="md:hidden">실행 </span>
                {x.runs.toLocaleString()}
              </span>
              <span className="text-xs text-slate-500 md:text-right md:text-sm md:text-slate-700">
                <span className="md:hidden">입력 </span>
                {x.input_tokens.toLocaleString()}
              </span>
              <span className="text-xs text-slate-500 md:text-right md:text-sm md:text-slate-700">
                <span className="md:hidden">출력 </span>
                {x.output_tokens.toLocaleString()}
              </span>
              <span className="text-xs text-slate-500 md:text-right md:text-sm md:text-slate-700">
                <span className="md:hidden">비용 </span>
                {formatCost(x.cost)}
              </span>
            </li>
          ))}
        </ul>
        <NoMatch c={c} />
      </Card>
      <ListPager c={c} />
    </div>
  );
}

/** 모델을 바꾸면 비용이 얼마일지(최근 30일 토큰 기준) */
export function CostEstimateCard({ ws }: { ws: string }) {
  const cat = useLlmCatalog();
  const choices = (cat.data ?? []).filter((m) => !m.embedding && m.input_price > 0);
  const [model, setModel] = useState("");
  const est = useCostEstimate(ws, model);
  return (
    <Card>
      <CardHeader
        title="모델을 바꾸면?"
        description="최근 30일 동안 쓴 토큰을 다른 모델로 썼다면 비용이 얼마였을지 계산해요."
      />
      <CardBody className="space-y-3">
        <Field label="비교할 모델" htmlFor="est-model">
          <Select id="est-model" value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="">모델 고르기</option>
            {choices.map((m) => (
              <option key={m.model} value={m.model}>
                {m.label}
              </option>
            ))}
          </Select>
        </Field>
        {est.isFetching && <Loading />}
        <ErrorBox error={est.error} />
        {est.data && (
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
            <div className="rounded-lg bg-slate-50 p-3">
              <p className="text-xs text-slate-500">지금 쓴 비용</p>
              <p className="text-lg font-semibold">{formatCost(est.data.current_cost)}</p>
            </div>
            <div className="rounded-lg bg-indigo-50 p-3">
              <p className="text-xs text-indigo-700">이 모델로 썼다면</p>
              <p className="text-lg font-semibold text-indigo-900">
                {formatCost(est.data.estimated_cost)}
              </p>
            </div>
            <div
              className={`col-span-2 rounded-lg p-3 sm:col-span-1 ${
                est.data.difference <= 0 ? "bg-emerald-50" : "bg-amber-50"
              }`}
            >
              <p className="text-xs text-slate-600">차이</p>
              <p className="text-lg font-semibold">
                {est.data.difference <= 0 ? "−" : "+"}
                {formatCost(Math.abs(est.data.difference))}
              </p>
            </div>
            <p className="col-span-2 text-xs text-slate-500 sm:col-span-3">
              입력 {est.data.input_tokens.toLocaleString()} · 출력{" "}
              {est.data.output_tokens.toLocaleString()} 토큰 기준. 모델마다 답의 길이가 달라 실제
              비용은 다를 수 있어요.
            </p>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function numOrNull(v: string): number | null {
  const t = v.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/** 월 한도·알림·보관 기간(소유자·관리자) */
export function LimitsCard({ ws }: { ws: string }) {
  const q = useLimits(ws);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  if (!q.data) return null;
  return <LimitsForm ws={ws} initial={q.data} />;
}

function LimitsForm({ ws, initial }: { ws: string; initial: WorkspaceLimits }) {
  const save = useUpdateLimits(ws);
  const creds = useCredentials(ws, true);
  const mailCreds = (creds.data ?? []).filter((c) => c.connector_key === "email");
  const [budget, setBudget] = useState(initial.monthly_budget_usd?.toString() ?? "");
  const [alertAt, setAlertAt] = useState(initial.cost_alert_usd?.toString() ?? "");
  const [onFail, setOnFail] = useState(initial.alert_on_failure);
  const [emails, setEmails] = useState(initial.alert_emails.join(", "));
  const [cred, setCred] = useState(initial.alert_credential_id ?? "");
  const [retention, setRetention] = useState(initial.retention_days?.toString() ?? "");
  const used = initial.month_cost;
  const ratio = initial.monthly_budget_usd ? Math.min(1, used / initial.monthly_budget_usd) : 0;

  return (
    <Card>
      <CardHeader
        title="한도·알림·보관 기간"
        description="이번 달 비용이 한도를 넘으면 새 실행을 멈추고, 실패·비용을 메일로 알려요."
      />
      <CardBody className="space-y-4">
        <div>
          <p className="text-sm">
            이번 달 비용 <b>{formatCost(used)}</b>
            {initial.monthly_budget_usd != null && (
              <span className="text-slate-500">
                {" "}
                / 한도 {formatCost(initial.monthly_budget_usd)}
              </span>
            )}
          </p>
          {initial.monthly_budget_usd != null && (
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100" aria-hidden>
              <div
                className={`h-full ${ratio >= 1 ? "bg-red-500" : ratio >= 0.8 ? "bg-amber-500" : "bg-indigo-500"}`}
                style={{ width: `${Math.round(ratio * 100)}%` }}
              />
            </div>
          )}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="월 한도(달러)" htmlFor="lim-budget" hint="비우면 제한이 없어요.">
            <Input
              id="lim-budget"
              inputMode="decimal"
              placeholder="예: 50"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
            />
          </Field>
          <Field
            label="비용 알림 기준(달러)"
            htmlFor="lim-alert"
            hint="이번 달 비용이 넘으면 한 번 알려요."
          >
            <Input
              id="lim-alert"
              inputMode="decimal"
              placeholder="예: 30"
              value={alertAt}
              onChange={(e) => setAlertAt(e.target.value)}
            />
          </Field>
          <Field label="알림 받을 메일(쉼표로 여러 명)" htmlFor="lim-emails">
            <Input
              id="lim-emails"
              placeholder="ops@example.com"
              value={emails}
              onChange={(e) => setEmails(e.target.value)}
            />
          </Field>
          <Field
            label="알림을 보낼 메일 연결 정보"
            htmlFor="lim-cred"
            hint={mailCreds.length ? undefined : "연결 정보에서 Email (SMTP)를 먼저 등록하세요."}
          >
            <Select id="lim-cred" value={cred} onChange={(e) => setCred(e.target.value)}>
              <option value="">고르지 않음(알림 안 보냄)</option>
              {mailCreds.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="기록 보관 기간(일)"
            htmlFor="lim-ret"
            hint="이보다 오래된 실행 기록·대화를 매일 지워요. 비우면 계속 보관해요(7~3650)."
          >
            <Input
              id="lim-ret"
              inputMode="numeric"
              placeholder="예: 180"
              value={retention}
              onChange={(e) => setRetention(e.target.value)}
            />
          </Field>
          <label className="flex items-center gap-2 self-end pb-2 text-sm">
            <input
              type="checkbox"
              className="accent-indigo-600"
              checked={onFail}
              onChange={(e) => setOnFail(e.target.checked)}
            />
            실행이 실패하면 메일로 알리기(5분마다 모아서)
          </label>
        </div>
        <ErrorBox error={save.error} />
        <Button
          disabled={save.isPending}
          onClick={() =>
            save.mutate(
              {
                monthly_budget_usd: numOrNull(budget),
                cost_alert_usd: numOrNull(alertAt),
                alert_on_failure: onFail,
                alert_emails: emails
                  .split(/[,;\s]+/)
                  .map((x) => x.trim())
                  .filter(Boolean),
                alert_credential_id: cred || null,
                retention_days: numOrNull(retention),
              },
              { onSuccess: () => toast.success("한도·알림 설정을 저장했어요.") },
            )
          }
        >
          {save.isPending ? "저장 중…" : "저장"}
        </Button>
      </CardBody>
    </Card>
  );
}
