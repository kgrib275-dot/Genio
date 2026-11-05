// v0.8 가져오기 소스: 웹사이트 여러 쪽·Notion·공개 Google 문서를 지식베이스에 연결하고 동기화한다.
import {
  CloudDownload,
  FileSpreadsheet,
  Globe,
  NotebookText,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState } from "@/components/EmptyState";
import { ErrorBox } from "@/components/ErrorBox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { useCredentials } from "@/lib/api/resources";
import {
  describeSummary,
  describeTarget,
  SOURCE_LABEL,
  sourceStatusLabel,
  useAddSource,
  useDeleteSource,
  useKbSources,
  usePatchSource,
  useSyncSource,
  type KbSource,
  type SourceType,
} from "@/lib/api/v8kb";
import { formatDate } from "@/lib/cn";

const ICON: Record<SourceType, typeof Globe> = {
  web: Globe,
  notion: NotebookText,
  google: FileSpreadsheet,
};

function lines(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

// ---------------- 추가 대화상자 ----------------
export function AddSourceDialog({
  ws,
  kbId,
  type,
  onClose,
}: {
  ws: string;
  kbId: string;
  type: SourceType;
  onClose: () => void;
}) {
  const add = useAddSource(kbId);
  const creds = useCredentials(ws, type === "notion");
  const notionCreds = (creds.data ?? []).filter((c) => c.connector_key === "notion");
  const [url, setUrl] = useState("");
  const [depth, setDepth] = useState(1);
  const [maxPages, setMaxPages] = useState(20);
  const [include, setInclude] = useState("");
  const [exclude, setExclude] = useState("");
  const [cred, setCred] = useState("");
  const [targets, setTargets] = useState("");
  const [children, setChildren] = useState(false);
  const [links, setLinks] = useState("");
  const [name, setName] = useState("");
  const [daily, setDaily] = useState(false);

  const config = (): Record<string, unknown> => {
    if (type === "web")
      return {
        url: url.trim(),
        depth,
        max_pages: maxPages,
        include: lines(include),
        exclude: lines(exclude),
      };
    if (type === "notion")
      return { credential_id: cred, targets: lines(targets), include_children: children };
    return { urls: lines(links), name: name.trim() };
  };
  const ready =
    type === "web"
      ? /^https?:\/\//.test(url.trim())
      : type === "notion"
        ? Boolean(cred) && lines(targets).length > 0
        : lines(links).length > 0;

  return (
    <Dialog
      open
      onClose={onClose}
      title={`${SOURCE_LABEL[type]} 가져오기`}
      wide
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            취소
          </Button>
          <Button
            disabled={!ready || add.isPending}
            onClick={() =>
              add.mutate(
                {
                  type,
                  name: type === "google" ? "" : name.trim(),
                  config: config(),
                  schedule: daily ? "daily" : "none",
                },
                {
                  onSuccess: (s) => {
                    toast.success(
                      s.last_status === "failed"
                        ? "연결은 만들었지만 가져오지 못했어요. 목록에서 이유를 확인하세요."
                        : "가져왔어요. 처리가 끝나면 문서가 '준비됨'으로 바뀌어요.",
                    );
                    onClose();
                  },
                },
              )
            }
          >
            <CloudDownload className="h-4 w-4" /> {add.isPending ? "가져오는 중…" : "가져오기"}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        {type === "web" && (
          <>
            <Field
              label="시작 주소"
              htmlFor="src-url"
              hint="이 사이트의 같은 도메인 쪽만 따라가요. 로그인이 필요하거나 사내망인 주소는 막혀 있어요."
            >
              <Input
                id="src-url"
                placeholder="https://docs.example.com/"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="따라갈 깊이" htmlFor="src-depth" hint="0 = 이 쪽만, 2 = 두 단계까지">
                <Select
                  id="src-depth"
                  value={depth}
                  onChange={(e) => setDepth(Number(e.target.value))}
                >
                  <option value={0}>0 · 이 쪽만</option>
                  <option value={1}>1 · 이 쪽에서 이어진 쪽</option>
                  <option value={2}>2 · 두 단계까지</option>
                </Select>
              </Field>
              <Field label="최대 쪽 수" htmlFor="src-max" hint="최대 50쪽">
                <Input
                  id="src-max"
                  type="number"
                  min={1}
                  max={50}
                  value={maxPages}
                  onChange={(e) =>
                    setMaxPages(Math.max(1, Math.min(50, Number(e.target.value) || 1)))
                  }
                />
              </Field>
            </div>
            <details className="rounded-lg border border-slate-200 px-3 py-2">
              <summary className="cursor-pointer text-xs font-medium text-slate-600">
                가져올 쪽·뺄 쪽 정하기(선택)
              </summary>
              <div className="mt-2 space-y-2">
                <Field
                  label="이런 주소만"
                  htmlFor="src-inc"
                  hint="줄마다 하나. 예: /docs 또는 /guide/*"
                >
                  <Textarea
                    id="src-inc"
                    rows={2}
                    value={include}
                    onChange={(e) => setInclude(e.target.value)}
                  />
                </Field>
                <Field label="이런 주소는 빼기" htmlFor="src-exc" hint="예: /blog, /login">
                  <Textarea
                    id="src-exc"
                    rows={2}
                    value={exclude}
                    onChange={(e) => setExclude(e.target.value)}
                  />
                </Field>
              </div>
            </details>
            <p className="text-xs text-slate-500">
              사이트의 robots.txt가 막은 쪽은 건너뛰고, 쪽 사이에 잠깐 쉬면서 천천히 가져와요. 같은
              쪽은 한 번만 가져오고, 다시 가져올 때는 바뀐 쪽만 고쳐요.
            </p>
          </>
        )}
        {type === "notion" && (
          <>
            <Field
              label="노션 연결 정보"
              htmlFor="src-cred"
              hint="'내부 통합 토큰'을 넣은 연결 정보예요."
            >
              <Select id="src-cred" value={cred} onChange={(e) => setCred(e.target.value)}>
                <option value="">고르세요</option>
                {notionCreds.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </Field>
            {!creds.isLoading && notionCreds.length === 0 && (
              <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
                노션 연결 정보가 아직 없어요.{" "}
                <Link to="/connectors" className="font-semibold underline">
                  연결 정보 화면
                </Link>
                에서 마켓의 '노션'을 설치하고 토큰을 넣어 주세요.
              </p>
            )}
            <Field
              label="가져올 페이지·데이터베이스"
              htmlFor="src-targets"
              hint="노션 주소를 줄마다 하나씩 붙여 넣으세요. 각 페이지에서 '연결 추가'로 통합을 초대해야 읽을 수 있어요."
            >
              <Textarea
                id="src-targets"
                rows={3}
                placeholder="https://www.notion.so/…"
                value={targets}
                onChange={(e) => setTargets(e.target.value)}
              />
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={children}
                onChange={(e) => setChildren(e.target.checked)}
              />
              하위 페이지도 가져오기
            </label>
          </>
        )}
        {type === "google" && (
          <>
            <Field
              label="Google 문서 주소"
              htmlFor="src-links"
              hint="문서·시트·슬라이드·드라이브 파일의 공유 링크를 줄마다 하나씩 붙여 넣으세요."
            >
              <Textarea
                id="src-links"
                rows={3}
                placeholder="https://docs.google.com/document/d/…"
                value={links}
                onChange={(e) => setLinks(e.target.value)}
              />
            </Field>
            {lines(links).length === 1 && (
              <Field label="이름(비우면 문서 제목)" htmlFor="src-gname">
                <Input id="src-gname" value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
            )}
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
              <b>링크가 있는 모든 사용자</b>가 볼 수 있게 공유된 문서만 가져올 수 있어요. 개인
              드라이브의 비공개 파일은 아직 연결할 수 없어요.
            </p>
          </>
        )}
        {type !== "google" && (
          <Field label="이름(선택)" htmlFor="src-name">
            <Input
              id="src-name"
              placeholder={type === "web" ? "예: 제품 설명서 사이트" : "예: 사내 위키"}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
        )}
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={daily} onChange={(e) => setDaily(e.target.checked)} />
          매일 한 번 자동으로 다시 가져오기
        </label>
        <ErrorBox error={add.error} />
      </div>
    </Dialog>
  );
}

// ---------------- 소스 줄 ----------------
function SourceRow({ kbId, s, editable }: { kbId: string; s: KbSource; editable: boolean }) {
  const sync = useSyncSource(kbId);
  const patch = usePatchSource(kbId);
  const del = useDeleteSource(kbId);
  const Icon = ICON[s.type];
  const st = sourceStatusLabel(s);
  const summary = describeSummary(s.last_summary);
  return (
    <li className="space-y-1.5 px-4 py-3 text-sm sm:px-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="flex min-w-0 flex-1 basis-48 items-center gap-1.5">
          <Icon className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          <span className="truncate font-medium" title={s.name}>
            {s.name}
          </span>
          <Badge tone="gray">{SOURCE_LABEL[s.type]}</Badge>
        </span>
        <Badge tone={st.tone}>{st.label}</Badge>
        {s.schedule === "daily" && <Badge tone="indigo">매일</Badge>}
        {editable && (
          <span className="ml-auto flex shrink-0 gap-0.5">
            <Button
              size="sm"
              variant="ghost"
              disabled={s.running || sync.isPending}
              aria-label={`${s.name} 지금 가져오기`}
              title="지금 가져오기"
              onClick={() =>
                sync.mutate(s.id, {
                  onSuccess: () => toast.success("가져오기를 시작했어요."),
                  onError: (err) => toast.error(err),
                })
              }
            >
              <RefreshCw className={`h-3.5 w-3.5 ${s.running ? "animate-spin" : ""}`} />
              <span className="hidden sm:inline">지금 가져오기</span>
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={patch.isPending}
              aria-label={`${s.name} 매일 가져오기 ${s.schedule === "daily" ? "끄기" : "켜기"}`}
              onClick={() =>
                patch.mutate(
                  { id: s.id, schedule: s.schedule === "daily" ? "none" : "daily" },
                  { onError: (err) => toast.error(err) },
                )
              }
            >
              {s.schedule === "daily" ? "매일 끄기" : "매일 켜기"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-red-600"
              aria-label={`${s.name} 지우기`}
              title="소스 지우기"
              onClick={() => {
                if (!window.confirm(`'${s.name}' 소스를 지울까요?`)) return;
                const withDocs = window.confirm(
                  "이 소스로 가져온 문서도 함께 지울까요?\n[확인] 문서도 지우기 · [취소] 문서는 남기기",
                );
                del.mutate(
                  { id: s.id, deleteDocuments: withDocs },
                  { onError: (err) => toast.error(err) },
                );
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </span>
        )}
      </div>
      <p className="truncate text-xs text-slate-500" title={describeTarget(s)}>
        {describeTarget(s)}
      </p>
      {s.running && s.progress && s.progress.total > 0 && (
        <div
          className="h-1.5 overflow-hidden rounded-full bg-slate-100"
          role="progressbar"
          aria-label="가져오기 진행"
          aria-valuemin={0}
          aria-valuemax={s.progress.total}
          aria-valuenow={s.progress.done}
        >
          <div
            className="h-full rounded-full bg-indigo-500 transition-all"
            style={{ width: `${Math.min(100, (s.progress.done / s.progress.total) * 100)}%` }}
          />
        </div>
      )}
      {!s.running && (summary || s.last_sync_at) && (
        <p className="text-xs text-slate-500">
          {s.last_sync_at && `${formatDate(s.last_sync_at)} · `}
          {summary}
        </p>
      )}
      {!s.running && s.last_error && (
        <p className="text-xs text-red-600" role="alert">
          {s.last_error}
        </p>
      )}
      {s.last_summary?.notes?.map((n) => (
        <p key={n} className="text-xs text-amber-700">
          {n}
        </p>
      ))}
      {s.last_summary?.failures && s.last_summary.failures.length > 0 && (
        <details className="text-xs text-slate-500">
          <summary className="cursor-pointer text-red-600">
            가져오지 못한 곳 {s.last_summary.failed}개
          </summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {s.last_summary.failures.map((f) => (
              <li key={f} className="break-all">
                {f}
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

export function SourcesCard({
  ws,
  kbId,
  editable,
  adding,
  onCloseAdd,
}: {
  ws: string;
  kbId: string;
  editable: boolean;
  /** 열려 있는 추가 대화상자 종류 */
  adding: SourceType | null;
  onCloseAdd: () => void;
}) {
  const sources = useKbSources(kbId);
  const list = sources.data ?? [];
  return (
    <>
      <Card>
        <CardHeader
          title="가져오기 소스"
          description="웹사이트·Notion·Google 문서를 연결해 두면 바뀐 내용만 다시 가져와요."
        />
        <CardBody className="p-0">
          <ErrorBox error={sources.error} />
          {sources.data && list.length === 0 && (
            <EmptyState
              compact
              icon={<CloudDownload className="h-5 w-5" />}
              title="아직 연결한 소스가 없어요"
              description="위의 '자료 추가'에서 웹사이트, Notion, Google 문서를 골라 한 번에 가져올 수 있어요."
            />
          )}
          <ul className="divide-y divide-slate-100 empty:hidden">
            {list.map((s) => (
              <SourceRow key={s.id} kbId={kbId} s={s} editable={editable} />
            ))}
          </ul>
        </CardBody>
      </Card>
      {adding && <AddSourceDialog ws={ws} kbId={kbId} type={adding} onClose={onCloseAdd} />}
    </>
  );
}
