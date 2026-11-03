import {
  BookMarked,
  Eye,
  EyeOff,
  FileUp,
  History,
  MessageSquareQuote,
  Mic,
  Plus,
  ShieldBan,
  Sparkles,
  Trash2,
  Variable,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Select, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { useApp, useApps } from "@/lib/api/apps";
import {
  normalizeFeatures,
  type AppDetailV2,
  type AppFeatures,
  type EnvVar,
} from "@/lib/api/types";
import { useSaveEnvVars, useSaveFeatures } from "@/lib/api/v2";
import { cn } from "@/lib/cn";
import { AppNav } from "@/pages/apps/AppNav";
import { canEdit, useSession } from "@/store/session";

function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50",
        checked ? "bg-indigo-600" : "bg-slate-300",
      )}
    >
      <span
        className={cn(
          "inline-block h-5 w-5 rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-5" : "translate-x-0.5",
        )}
      />
    </button>
  );
}

function FeatureRow({
  icon,
  title,
  description,
  enabled,
  onToggle,
  children,
  disabled,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  enabled?: boolean;
  onToggle?: (v: boolean) => void;
  children?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <div className="border-b border-slate-100 px-4 py-4 last:border-b-0 sm:px-5">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-slate-800">{title}</p>
          <p className="text-xs text-slate-500">{description}</p>
        </div>
        {onToggle && (
          <Toggle
            checked={Boolean(enabled)}
            onChange={onToggle}
            label={title}
            disabled={disabled}
          />
        )}
      </div>
      {children && (onToggle === undefined || enabled) && (
        <div className="mt-3 space-y-3 sm:pl-11">{children}</div>
      )}
    </div>
  );
}

function ListEditor({
  values,
  onChange,
  placeholder,
  addLabel,
  disabled,
}: {
  values: string[];
  onChange: (v: string[]) => void;
  placeholder: string;
  addLabel: string;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-2">
      {values.map((v, i) => (
        <div key={i} className="flex gap-2">
          <Input
            aria-label={`${placeholder} ${i + 1}`}
            value={v}
            disabled={disabled}
            placeholder={placeholder}
            onChange={(e) => onChange(values.map((x, j) => (j === i ? e.target.value : x)))}
          />
          <Button
            variant="ghost"
            size="sm"
            className="h-10 text-slate-400"
            aria-label="지우기"
            disabled={disabled}
            onClick={() => onChange(values.filter((_, j) => j !== i))}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}
      <Button
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={() => onChange([...values, ""])}
      >
        <Plus className="h-3.5 w-3.5" /> {addLabel}
      </Button>
    </div>
  );
}

/** 앱 기능 편집 폼. 저장 시 PATCH /apps/{id}/features 로 전체 features를 보낸다. */
export function FeaturesForm({
  initial,
  onSave,
  saving,
  readOnly,
}: {
  initial: AppFeatures;
  onSave: (f: AppFeatures) => void;
  saving?: boolean;
  readOnly?: boolean;
}) {
  const [f, setF] = useState<AppFeatures>(initial);
  const [keywordsText, setKeywordsText] = useState(initial.moderation.keywords.join("\n"));
  useEffect(() => {
    setF(initial);
    setKeywordsText(initial.moderation.keywords.join("\n"));
  }, [initial]);

  const save = () => {
    const keywords = keywordsText
      .split(/[\n,]/)
      .map((k) => k.trim())
      .filter(Boolean);
    onSave({
      ...f,
      suggested_questions: f.suggested_questions.map((q) => q.trim()).filter(Boolean),
      moderation: { ...f.moderation, keywords },
    });
  };

  return (
    <Card className="overflow-hidden">
      <CardHeader
        title="앱 기능"
        description="챗봇을 쓰는 사람에게 보이는 기능을 켜고 끄요."
        action={
          !readOnly && (
            <Button size="sm" disabled={saving} onClick={save}>
              {saving ? "저장 중…" : "저장"}
            </Button>
          )
        }
      />
      <div className="border-t border-slate-100">
        <FeatureRow
          icon={<MessageSquareQuote className="h-4 w-4" />}
          title="시작 인사·추천 질문"
          description="처음 열었을 때 보이는 인사와 눌러 볼 수 있는 질문이에요."
        >
          <Textarea
            aria-label="시작 인사"
            placeholder="예: 안녕하세요! 사내 규정에 대해 무엇이든 물어보세요."
            value={f.opening_statement}
            disabled={readOnly}
            onChange={(e) => setF({ ...f, opening_statement: e.target.value })}
          />
          <ListEditor
            values={f.suggested_questions}
            onChange={(v) => setF({ ...f, suggested_questions: v })}
            placeholder="추천 질문"
            addLabel="추천 질문 추가"
            disabled={readOnly}
          />
        </FeatureRow>
        <FeatureRow
          icon={<Sparkles className="h-4 w-4" />}
          title="이어서 물어볼 질문"
          description="답 뒤에 다음에 물어볼 만한 질문 3개를 보여 줘요."
          enabled={f.follow_up.enabled}
          disabled={readOnly}
          onToggle={(v) => setF({ ...f, follow_up: { enabled: v } })}
        />
        <FeatureRow
          icon={<BookMarked className="h-4 w-4" />}
          title="출처 표시"
          description="지식 검색으로 찾은 문서를 답 아래에 번호로 보여 줘요."
          enabled={f.citations.enabled}
          disabled={readOnly}
          onToggle={(v) => setF({ ...f, citations: { enabled: v } })}
        />
        <FeatureRow
          icon={<ShieldBan className="h-4 w-4" />}
          title="내용 검열"
          description="금지어가 들어간 질문(과 답)을 미리 정한 답으로 바꿔요."
          enabled={f.moderation.enabled}
          disabled={readOnly}
          onToggle={(v) => setF({ ...f, moderation: { ...f.moderation, enabled: v } })}
        >
          <label className="block space-y-1 text-xs">
            <span className="font-medium text-slate-600">
              금지어(줄마다 하나, 또는 쉼표로 구분)
            </span>
            <Textarea
              aria-label="금지어"
              value={keywordsText}
              disabled={readOnly}
              onChange={(e) => setKeywordsText(e.target.value)}
            />
          </label>
          <label className="block space-y-1 text-xs">
            <span className="font-medium text-slate-600">대신 보낼 답</span>
            <Input
              aria-label="대신 보낼 답"
              placeholder="예: 그 내용에는 답할 수 없어요."
              value={f.moderation.preset_reply}
              disabled={readOnly}
              onChange={(e) =>
                setF({ ...f, moderation: { ...f.moderation, preset_reply: e.target.value } })
              }
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={f.moderation.check_output}
              disabled={readOnly}
              onChange={(e) =>
                setF({ ...f, moderation: { ...f.moderation, check_output: e.target.checked } })
              }
            />
            AI 답도 검사하기
          </label>
        </FeatureRow>
        <FeatureRow
          icon={<MessageSquareQuote className="h-4 w-4" />}
          title="주석 답변"
          description="로그·주석에 적어 둔 질문과 비슷하면 정해 둔 답을 바로 줘요."
          enabled={f.annotation_reply.enabled}
          disabled={readOnly}
          onToggle={(v) => setF({ ...f, annotation_reply: { ...f.annotation_reply, enabled: v } })}
        >
          <label className="block space-y-1 text-xs">
            <span className="font-medium text-slate-600">
              얼마나 비슷해야 할까요? ({f.annotation_reply.score_threshold.toFixed(2)})
            </span>
            <input
              type="range"
              min={0.5}
              max={1}
              step={0.01}
              aria-label="주석 답변 유사도 기준"
              className="w-full accent-indigo-600"
              value={f.annotation_reply.score_threshold}
              disabled={readOnly}
              onChange={(e) =>
                setF({
                  ...f,
                  annotation_reply: {
                    ...f.annotation_reply,
                    score_threshold: Number(e.target.value),
                  },
                })
              }
            />
          </label>
        </FeatureRow>
        <FeatureRow
          icon={<Mic className="h-4 w-4" />}
          title="음성"
          description="말로 묻기와 답 읽어 주기(브라우저가 지원할 때)."
        >
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <Toggle
                checked={f.speech.stt}
                label="음성 입력"
                disabled={readOnly}
                onChange={(v) => setF({ ...f, speech: { ...f.speech, stt: v } })}
              />
              음성 입력
            </label>
            <label className="flex items-center gap-2">
              <Toggle
                checked={f.speech.tts}
                label="읽어 주기"
                disabled={readOnly}
                onChange={(v) => setF({ ...f, speech: { ...f.speech, tts: v } })}
              />
              읽어 주기
            </label>
          </div>
        </FeatureRow>
        <FeatureRow
          icon={<FileUp className="h-4 w-4" />}
          title="파일 첨부"
          description="사용자가 챗에 파일을 붙일 수 있어요. 흐름의 '문서 읽기' 노드로 읽어요."
          enabled={f.file_upload.enabled}
          disabled={readOnly}
          onToggle={(v) => setF({ ...f, file_upload: { ...f.file_upload, enabled: v } })}
        >
          <label className="flex items-center gap-2 text-xs text-slate-600">
            한 번에 최대
            <Input
              type="number"
              min={1}
              max={10}
              className="h-8 w-20"
              aria-label="최대 파일 수"
              value={f.file_upload.max_files}
              disabled={readOnly}
              onChange={(e) =>
                setF({
                  ...f,
                  file_upload: {
                    ...f.file_upload,
                    max_files: Math.max(1, Math.min(10, Number(e.target.value) || 1)),
                  },
                })
              }
            />
            개
          </label>
        </FeatureRow>
        <FeatureRow
          icon={<History className="h-4 w-4" />}
          title="대화 기억"
          description="최근 대화 몇 번을 AI에게 함께 보내요. 0이면 기억하지 않아요."
        >
          <label className="flex items-center gap-3 text-xs text-slate-600">
            <input
              type="range"
              min={0}
              max={20}
              aria-label="대화 기억 횟수"
              className="flex-1 accent-indigo-600"
              value={f.memory.window}
              disabled={readOnly}
              onChange={(e) => setF({ ...f, memory: { window: Number(e.target.value) } })}
            />
            <span className="w-12 text-right font-medium">{f.memory.window}번</span>
          </label>
        </FeatureRow>
      </div>
    </Card>
  );
}

function EnvVarsCard({ app, readOnly }: { app: AppDetailV2; readOnly: boolean }) {
  const save = useSaveEnvVars(app.id);
  const [rows, setRows] = useState<EnvVar[]>(app.env_vars ?? []);
  const [shown, setShown] = useState<Record<number, boolean>>({});
  useEffect(() => setRows(app.env_vars ?? []), [app.env_vars]);
  const invalid = rows.some((r) => !/^[A-Za-z_][A-Za-z0-9_]*$/.test(r.key));
  const dup = new Set(rows.map((r) => r.key)).size !== rows.length;

  return (
    <Card>
      <CardHeader
        title="환경 변수"
        description={"흐름 어디서나 {{env.이름}}으로 써요. 비밀 값은 암호화되고 가려져요."}
        action={
          !readOnly && (
            <Button
              size="sm"
              disabled={save.isPending || invalid || dup}
              onClick={() =>
                save.mutate(rows, {
                  onSuccess: () => toast.success("환경 변수를 저장했어요."),
                  onError: (err) => toast.error(err),
                })
              }
            >
              저장
            </Button>
          )
        }
      />
      <CardBody className="space-y-2">
        {rows.length === 0 && <p className="text-sm text-slate-500">아직 환경 변수가 없어요.</p>}
        {rows.map((r, i) => (
          <div
            key={i}
            className="grid grid-cols-[1fr_auto] gap-2 sm:grid-cols-[10rem_1fr_auto_auto]"
          >
            <Input
              aria-label={`이름 ${i + 1}`}
              placeholder="이름(영문)"
              value={r.key}
              disabled={readOnly}
              className="font-mono text-xs sm:col-auto"
              onChange={(e) =>
                setRows(rows.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))
              }
            />
            <div className="relative col-span-2 sm:col-span-1">
              <Input
                aria-label={`값 ${i + 1}`}
                placeholder="값"
                type={r.secret && !shown[i] ? "password" : "text"}
                autoComplete="off"
                value={r.value}
                disabled={readOnly}
                className="pr-9 font-mono text-xs"
                onChange={(e) =>
                  setRows(rows.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))
                }
              />
              {r.secret && (
                <button
                  type="button"
                  aria-label={shown[i] ? "값 가리기" : "값 보기"}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400"
                  onClick={() => setShown({ ...shown, [i]: !shown[i] })}
                >
                  {shown[i] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              )}
            </div>
            <label className="flex items-center gap-1.5 whitespace-nowrap text-xs text-slate-600">
              <input
                type="checkbox"
                checked={r.secret}
                disabled={readOnly}
                onChange={(e) =>
                  setRows(rows.map((x, j) => (j === i ? { ...x, secret: e.target.checked } : x)))
                }
              />
              비밀
            </label>
            <Button
              variant="ghost"
              size="sm"
              className="h-10 text-slate-400"
              aria-label="변수 지우기"
              disabled={readOnly}
              onClick={() => setRows(rows.filter((_, j) => j !== i))}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}
        {(invalid || dup) && rows.length > 0 && (
          <p className="text-xs text-red-600">
            {dup
              ? "같은 이름이 두 번 있어요."
              : "이름은 영문·숫자·밑줄만 쓰고, 숫자로 시작할 수 없어요."}
          </p>
        )}
        {!readOnly && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => setRows([...rows, { key: "", value: "", secret: false }])}
          >
            <Variable className="h-3.5 w-3.5" /> 변수 추가
          </Button>
        )}
        <ErrorBox error={save.error} />
      </CardBody>
    </Card>
  );
}

/** 실행이 실패하면 다른 앱을 실행한다(알림·기록용 앱 등) */
function OnFailureCard({
  appId,
  wsId,
  features,
  readOnly,
  saving,
  onSave,
}: {
  appId: string;
  wsId: string;
  features: AppFeatures;
  readOnly: boolean;
  saving: boolean;
  onSave: (f: AppFeatures) => void;
}) {
  const apps = useApps(wsId);
  const current = features.on_failure?.app_id ?? "";
  const [pick, setPick] = useState(current);
  useEffect(() => setPick(current), [current]);
  const others = (apps.data ?? []).filter((a) => a.id !== appId);
  const chosen = others.find((a) => a.id === pick);
  return (
    <Card>
      <CardHeader
        title="실패했을 때"
        description="이 앱의 실행이 실패하면 고른 앱을 대신 실행해요. 담당자에게 알리거나 기록을 남길 때 써요."
        action={
          !readOnly && (
            <Button
              size="sm"
              disabled={saving || pick === current}
              onClick={() => onSave({ ...features, on_failure: { app_id: pick || null } })}
            >
              저장
            </Button>
          )
        }
      />
      <CardBody className="space-y-2">
        <label className="block space-y-1 text-xs">
          <span className="font-medium text-slate-600">실패하면 실행할 앱</span>
          <Select
            aria-label="실패하면 실행할 앱"
            value={pick}
            disabled={readOnly}
            onChange={(e) => setPick(e.target.value)}
          >
            <option value="">실행하지 않음</option>
            {others.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
                {a.latest_version ? "" : " (저장한 버전 없음)"}
              </option>
            ))}
          </Select>
        </label>
        <p className="text-xs text-slate-500">
          고른 앱은 이런 값을 입력으로 받아요: <code>failed_app_name</code>(실패한 앱 이름),{" "}
          <code>error</code>(오류 내용), <code>run_id</code>, <code>input</code>(원래 입력).
        </p>
        {chosen && !chosen.latest_version && (
          <p className="text-xs text-amber-700">
            {chosen.name}에 저장한 버전이 없어요. 그 앱에서 버전 저장을 먼저 하세요.
          </p>
        )}
      </CardBody>
    </Card>
  );
}

export default function AppFeaturesPage() {
  const { id: appId = "" } = useParams();
  const role = useSession((s) => s.role);
  const app = useApp(appId);
  const saveFeatures = useSaveFeatures(appId);
  const readOnly = !canEdit(role);
  const detail = app.data as AppDetailV2 | undefined;
  const features = useMemo(() => normalizeFeatures(detail?.features), [detail?.features]);

  return (
    <div className="flex min-h-full flex-col">
      <AppNav appId={appId} title={detail?.name ?? ""} icon={detail?.icon} help="features" />
      <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6">
        {app.isLoading && <Loading />}
        <ErrorBox error={app.error} />
        {detail && (
          <>
            <FeaturesForm
              initial={features}
              readOnly={readOnly}
              saving={saveFeatures.isPending}
              onSave={(f) =>
                saveFeatures.mutate(f, {
                  onSuccess: () => toast.success("앱 기능을 저장했어요."),
                  onError: (err) => toast.error(err),
                })
              }
            />
            <OnFailureCard
              appId={appId}
              wsId={detail.workspace_id}
              features={features}
              readOnly={readOnly}
              saving={saveFeatures.isPending}
              onSave={(f) =>
                saveFeatures.mutate(f, {
                  onSuccess: () => toast.success("실패했을 때 할 일을 저장했어요."),
                  onError: (err) => toast.error(err),
                })
              }
            />
            <EnvVarsCard app={detail} readOnly={readOnly} />
          </>
        )}
      </div>
    </div>
  );
}
