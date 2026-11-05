// 공개 API 문서(/api-docs): 다른 시스템이 제니오 앱을 부를 때 쓰는 API를 읽기 쉽게 보여 준다.
// 서버의 OpenAPI 문서(공개 경로·서비스 API·웹훅·MCP만)를 그대로 읽어 방식·주소·매개변수·요청·응답·curl 예시를 만든다.
import { ArrowLeft, Check, ChevronDown, ChevronRight, Copy, Search, Terminal } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useLoggedIn } from "@/app/useAuthState";
import { Logo } from "@/app/Layout";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { usePublicOpenApi } from "@/lib/api/apiDocs";
import { cn, copyText } from "@/lib/cn";
import {
  authOf,
  curlExample,
  groupEndpoints,
  resolveRef,
  schemaRows,
  type Endpoint,
  type OpenApiDoc,
  type SchemaRow,
} from "@/lib/openapi";

const METHOD_TONE: Record<string, string> = {
  get: "bg-emerald-50 text-emerald-700",
  post: "bg-indigo-50 text-indigo-700",
  put: "bg-amber-50 text-amber-700",
  patch: "bg-amber-50 text-amber-700",
  delete: "bg-red-50 text-red-700",
};

function MethodBadge({ method }: { method: string }) {
  return (
    <span
      className={cn(
        "inline-flex w-14 shrink-0 justify-center rounded-md py-0.5 font-mono text-[11px] font-bold uppercase",
        METHOD_TONE[method] ?? "bg-slate-100 text-slate-700",
      )}
    >
      {method}
    </span>
  );
}

function CopyBlock({ code, label }: { code: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="relative">
      <pre
        aria-label={label}
        className="overflow-x-auto rounded-xl bg-slate-100 px-4 py-3 pr-12 font-mono text-[12px] leading-relaxed text-slate-800"
      >
        {code}
      </pre>
      <button
        type="button"
        aria-label={`${label} 복사`}
        onClick={async () => {
          if (await copyText(code)) {
            setDone(true);
            window.setTimeout(() => setDone(false), 1500);
          }
        }}
        className="absolute right-2 top-2 rounded-md p-1.5 text-slate-500 hover:bg-slate-200 hover:text-slate-800"
      >
        {done ? <Check className="h-4 w-4 text-emerald-600" /> : <Copy className="h-4 w-4" />}
      </button>
    </div>
  );
}

function Table({ rows, empty }: { rows: SchemaRow[]; empty?: string }) {
  if (!rows.length) return empty ? <p className="text-xs text-slate-400">{empty}</p> : null;
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full min-w-[480px] text-left text-xs">
        <thead className="bg-slate-50 text-slate-500">
          <tr>
            <th className="px-3 py-1.5 font-medium">이름</th>
            <th className="px-3 py-1.5 font-medium">형식</th>
            <th className="px-3 py-1.5 font-medium">필수</th>
            <th className="px-3 py-1.5 font-medium">설명</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r) => (
            <tr key={r.name}>
              <td className="px-3 py-1.5 font-mono text-slate-800">{r.name}</td>
              <td className="px-3 py-1.5 text-slate-600">{r.type}</td>
              <td className="px-3 py-1.5">
                {r.required ? <span className="font-semibold text-red-600">필수</span> : "선택"}
              </td>
              <td className="px-3 py-1.5 text-slate-500">{r.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const WHERE: Record<string, string> = {
  path: "주소",
  query: "물음표 뒤",
  header: "헤더",
  cookie: "쿠키",
};

function EndpointCard({
  doc,
  ep,
  tag,
  origin,
  defaultOpen,
}: {
  doc: OpenApiDoc;
  ep: Endpoint;
  tag: string;
  origin: string;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = `${ep.method}-${ep.path}`.replace(/[^a-z0-9]+/gi, "-");
  const params: SchemaRow[] = (ep.op.parameters ?? []).map((p) => ({
    name: p.name,
    type: `${WHERE[p.in] ?? p.in} · ${resolveRef(doc, p.schema).type ?? "값"}`,
    required: Boolean(p.required),
    description: p.description ?? "",
  }));
  const bodySchema = ep.op.requestBody?.content?.["application/json"]?.schema;
  const bodyRows = bodySchema ? schemaRows(doc, bodySchema) : [];
  const multipart = Boolean(ep.op.requestBody?.content?.["multipart/form-data"]);
  const responses = Object.entries(ep.op.responses ?? {}).filter(([c]) => c !== "422");
  return (
    <article
      id={id}
      className="scroll-mt-20 overflow-hidden rounded-xl border border-slate-200 bg-white"
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-50"
      >
        <MethodBadge method={ep.method} />
        <code className="min-w-0 flex-1 truncate font-mono text-[13px] text-slate-800">
          {ep.path}
        </code>
        <span className="hidden text-sm text-slate-500 sm:inline">{ep.summary}</span>
        {open ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-slate-400" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-slate-400" />
        )}
      </button>
      {open && (
        <div className="space-y-4 border-t border-slate-100 px-4 py-4 text-sm">
          <p className="font-medium text-slate-800 sm:hidden">{ep.summary}</p>
          {ep.description && <p className="whitespace-pre-line text-slate-600">{ep.description}</p>}
          <p className="text-xs text-slate-500">
            <b className="text-slate-600">인증</b> · {authOf(tag).note}
          </p>
          {params.length > 0 && (
            <section>
              <h4 className="mb-1.5 text-xs font-semibold text-slate-500">매개변수</h4>
              <Table rows={params} />
            </section>
          )}
          {(bodyRows.length > 0 || multipart) && (
            <section>
              <h4 className="mb-1.5 text-xs font-semibold text-slate-500">
                보내는 내용{multipart ? "(파일 올리기)" : "(JSON)"}
              </h4>
              {multipart ? (
                <p className="text-xs text-slate-500">
                  <code>file</code> 칸에 파일을 담아 multipart/form-data로 보내요.
                </p>
              ) : (
                <Table rows={bodyRows} />
              )}
            </section>
          )}
          {responses.length > 0 && (
            <section>
              <h4 className="mb-1.5 text-xs font-semibold text-slate-500">응답</h4>
              <ul className="space-y-1 text-xs text-slate-600">
                {responses.map(([code, r]) => (
                  <li key={code}>
                    <code className="mr-2 rounded bg-slate-100 px-1.5 py-0.5 font-mono">
                      {code}
                    </code>
                    {r.description === "Successful Response" ? "성공" : r.description}
                  </li>
                ))}
                <li>
                  <code className="mr-2 rounded bg-slate-100 px-1.5 py-0.5 font-mono">4xx</code>
                  오류는 <code>{`{"detail": {"message": "…", "hint": "…"}}`}</code> 두 줄로 와요.
                </li>
              </ul>
            </section>
          )}
          <section>
            <h4 className="mb-1.5 text-xs font-semibold text-slate-500">curl 예시</h4>
            <CopyBlock code={curlExample(doc, ep, tag, origin)} label="curl 예시" />
          </section>
        </div>
      )}
    </article>
  );
}

const CLI_EXAMPLE = `export GENIO_URL=${typeof window === "undefined" ? "https://내-제니오-주소" : window.location.origin}
export GENIO_API_KEY=gk-내_API_키
python scripts/genio_cli.py info                       # 앱 정보와 입력 칸
python scripts/genio_cli.py run -i city=도쿄 -i days:=3  # 흐름 실행(결과까지 기다림)
python scripts/genio_cli.py chat "휴가 규정 알려줘"       # 대화 보내기`;

export default function ApiDocsPage() {
  const doc = usePublicOpenApi();
  const loggedIn = useLoggedIn();
  const [q, setQ] = useState("");
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const groups = useMemo(() => (doc.data ? groupEndpoints(doc.data, q) : []), [doc.data, q]);
  const total = groups.reduce((n, g) => n + g.endpoints.length, 0);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4 sm:px-8">
          <Logo />
          <span className="hidden text-sm font-semibold text-slate-500 sm:inline">
            공개 API 문서
          </span>
          <Link
            to={loggedIn ? "/" : "/login"}
            className="ml-auto inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100"
          >
            <ArrowLeft className="h-4 w-4" /> {loggedIn ? "앱으로 돌아가기" : "로그인"}
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-8 sm:py-8">
        <h1 className="text-xl font-bold tracking-tight sm:text-2xl">제니오 공개 API</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          다른 프로그램에서 제니오 앱을 부를 때 쓰는 API예요. 앱의 <b>API 화면</b>에서 키를 만들고,
          아래에서 주소와 보낼 내용을 확인하세요. 관리용 API는 담지 않았어요.
        </p>

        <section className="mt-5 grid gap-3 md:grid-cols-3" aria-label="시작하기">
          {[
            [
              "1. 키 만들기",
              "앱 > API 화면에서 '키 만들기'. 키는 만들 때 한 번만 보여요. 필요한 권한(대화·흐름 실행·기록 읽기·MCP)만 켜세요.",
            ],
            [
              "2. 부르기",
              "서비스 API는 헤더에 Authorization: Bearer gk-키 를 붙여요. 공유 링크 앱은 공유 주소의 토큰으로, 외부에서 받기는 비밀 주소로 불러요.",
            ],
            [
              "3. 오류 보기",
              "실패하면 상태 코드와 함께 {message, hint} 두 줄이 와요. 요청이 너무 많으면 429가 오니 잠시 뒤 다시 보내세요.",
            ],
          ].map(([t, d]) => (
            <div key={t} className="rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-sm font-semibold text-slate-800">{t}</p>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">{d}</p>
            </div>
          ))}
        </section>

        <section
          className="mt-4 rounded-xl border border-slate-200 bg-white p-4"
          aria-label="명령줄 도구"
        >
          <p className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-slate-800">
            <Terminal className="h-4 w-4 text-indigo-500" aria-hidden /> 명령줄 도구
          </p>
          <p className="mb-2 text-xs text-slate-500">
            터미널·스크립트·CI에서 쓰는 작은 도구예요(파이썬만 있으면 돼요, 설치할 것 없음). 키
            하나는 앱 하나에 묶여 있어요.
          </p>
          <CopyBlock code={CLI_EXAMPLE} label="명령줄 도구 사용 예" />
        </section>

        <div className="mt-6 flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3">
          <Search className="h-4 w-4 text-slate-400" aria-hidden />
          <input
            aria-label="API 찾기"
            placeholder="경로·이름으로 찾기 (예: chat, runs, 파일)"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="h-10 w-full bg-transparent text-sm placeholder:text-slate-400 focus:outline-none"
          />
          <span className="shrink-0 text-xs text-slate-400">{total}개</span>
        </div>

        {doc.isLoading && <Loading />}
        <ErrorBox error={doc.error} />
        <div className="mt-5 grid gap-6 lg:grid-cols-[220px_1fr]">
          <nav aria-label="묶음" className="hidden lg:block">
            <ul className="sticky top-20 space-y-1 text-sm">
              {groups.map((g) => (
                <li key={g.tag}>
                  <a
                    href={`#tag-${g.tag}`}
                    className="flex items-center justify-between rounded-lg px-3 py-1.5 text-slate-600 hover:bg-slate-100"
                  >
                    <span className="truncate">{g.tag}</span>
                    <span className="text-xs text-slate-400">{g.endpoints.length}</span>
                  </a>
                </li>
              ))}
            </ul>
          </nav>
          <div className="min-w-0 space-y-8">
            {doc.data &&
              groups.map((g) => (
                <section key={g.tag} id={`tag-${g.tag}`} className="scroll-mt-20 space-y-3">
                  <div>
                    <h2 className="text-lg font-bold tracking-tight">{g.tag}</h2>
                    {g.description && <p className="text-sm text-slate-500">{g.description}</p>}
                  </div>
                  {g.endpoints.map((ep) => (
                    <EndpointCard
                      key={`${ep.method}${ep.path}`}
                      doc={doc.data}
                      ep={ep}
                      tag={g.tag}
                      origin={origin}
                      defaultOpen={total <= 3}
                    />
                  ))}
                </section>
              ))}
            {doc.data && groups.length === 0 && (
              <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
                “{q}”에 맞는 API가 없어요. 다른 낱말로 찾아 보세요.
              </p>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
