import { Link, useParams } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { JsonView } from "@/components/canvas/RunPanel";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { toast } from "@/components/ui/toast-store";
import { ko } from "@/i18n/ko";
import { useInstallMarketItem, useMarketItem } from "@/lib/api/resources";
import type { TemplatePreview } from "@/lib/api/v5b";
import { canManage, useSession } from "@/store/session";

/** 템플릿 미리 보기: 어떤 단계로 이루어졌는지, 설치 뒤 채울 빈칸은 무엇인지 */
function PreviewCard({ preview }: { preview: TemplatePreview }) {
  return (
    <Card>
      <CardHeader
        title="미리 보기"
        description={`${preview.app_type === "chat" ? "챗봇" : "흐름"} · 단계 ${preview.steps.length}개`}
      />
      <CardBody className="space-y-4">
        <ol className="space-y-1.5">
          {preview.steps.map((st, i) => (
            <li key={st.id} className="flex items-center gap-2 text-sm">
              <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-50 text-[11px] font-semibold text-indigo-700">
                {i + 1}
              </span>
              <span className="font-medium text-slate-800">{st.label}</span>
              <span className="text-xs text-slate-500">{st.kind}</span>
              {st.service && <Badge tone="blue">{st.service}</Badge>}
            </li>
          ))}
        </ol>
        {preview.requires.length > 0 && (
          <p className="text-xs text-slate-600">
            함께 필요한 서비스: <b>{preview.requires.join(", ")}</b> (설치할 때 같이 확인해요)
          </p>
        )}
        {preview.blanks.length > 0 && (
          <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
            <p className="mb-1 font-medium">설치한 뒤 빌더가 이것만 물어봐요</p>
            <ul className="list-disc space-y-0.5 pl-4">
              {preview.blanks.map((b) => (
                <li key={b.key}>
                  {b.label}
                  {b.example ? ` (예: ${b.example})` : ""}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

export default function MarketDetailPage() {
  const { key = "" } = useParams();
  const { workspaceId: ws, role } = useSession();
  const item = useMarketItem(key, ws);
  const install = useInstallMarketItem(ws);

  return (
    <PageContainer>
      <Link to="/market" className="text-sm text-indigo-600 hover:underline">
        ← 마켓
      </Link>
      {item.isLoading && <Loading />}
      <ErrorBox error={item.error} />
      {item.data && (
        <div className="mt-4 grid gap-6 lg:grid-cols-[2fr_1fr]">
          <div className="space-y-6">
            <Card>
              <CardHeader
                title={item.data.name}
                description={item.data.summary}
                action={
                  <Badge tone="indigo">{ko.marketTypes[item.data.type] ?? item.data.type}</Badge>
                }
              />
              <CardBody>
                <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
                  {item.data.description_md || "설명이 없어요."}
                </div>
              </CardBody>
            </Card>
            {(item.data as { preview?: TemplatePreview }).preview && (
              <PreviewCard
                preview={(item.data as { preview?: TemplatePreview }).preview as TemplatePreview}
              />
            )}
          </div>
          <div className="space-y-4">
            <Card>
              <CardBody className="space-y-2 text-sm">
                <p>
                  가격:{" "}
                  <b>
                    {item.data.price > 0
                      ? `${item.data.price.toLocaleString()}원 (모의 결제)`
                      : "무료"}
                  </b>
                </p>
                <p>제공: {item.data.publisher}</p>
                {(item.data as { category?: string }).category && (
                  <p>분류: {(item.data as { category?: string }).category}</p>
                )}
                <p>버전: {item.data.version}</p>
                <p>설치 수: {item.data.installs}</p>
                {item.data.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {item.data.tags.map((t) => (
                      <Badge key={t}>{t}</Badge>
                    ))}
                  </div>
                )}
                <div className="pt-2">
                  {item.data.installed ? (
                    <Badge tone="green">이 워크스페이스에 설치됨</Badge>
                  ) : canManage(role) ? (
                    <Button
                      disabled={install.isPending}
                      onClick={() =>
                        install.mutate(key, {
                          onSuccess: () => toast.success("설치했어요. 이제 흐름에서 쓸 수 있어요."),
                        })
                      }
                    >
                      {install.isPending ? "설치 중…" : "설치하기"}
                    </Button>
                  ) : (
                    <p className="text-xs text-slate-500">설치는 관리자만 할 수 있어요.</p>
                  )}
                </div>
                <ErrorBox error={install.error} />
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="구성 정보" description="개발자용 상세(manifest)" />
              <CardBody>
                <JsonView value={item.data.manifest} />
              </CardBody>
            </Card>
          </div>
        </div>
      )}
    </PageContainer>
  );
}
