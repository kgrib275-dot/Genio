// 운영 준비 1차(B2): 개인정보 가리기(소유자·관리자)
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { toast } from "@/components/ui/toast-store";
import { usePrivacy, useUpdatePrivacy, type PrivacySettings } from "@/lib/api/privacy";

const OPTIONS: { key: keyof PrivacySettings; label: string; hint: string }[] = [
  {
    key: "mask_logs",
    label: "기록에서 개인정보 가리기",
    hint: "실행 기록·대화 로그·외부 추적에서 주민번호·전화·카드·계좌·메일·여권번호를 [전화번호]처럼 가려서 보여요. 상담원이 응대 중인 대화는 그대로 보여요.",
  },
  {
    key: "mask_before_ai",
    label: "AI에 보내기 전에 항상 가리기",
    hint: "모든 AI 단계에서 개인정보를 가린 채 AI 서비스로 보내고, 답에 나오면 원래 값으로 돌려 넣어요. 단계마다 켜려면 AI 단계의 '개인정보 가리고 보내기'를 쓰세요.",
  },
];

export function PrivacyCard({ ws }: { ws: string }) {
  const q = usePrivacy(ws);
  const save = useUpdatePrivacy(ws);
  return (
    <Card>
      <CardHeader
        title="개인정보 가리기"
        description="기록과 AI 서비스에 개인정보가 그대로 남거나 넘어가지 않게 해요."
      />
      <CardBody className="space-y-3">
        {q.isLoading && <Loading />}
        <ErrorBox error={q.error ?? save.error} />
        {q.data &&
          OPTIONS.map((o) => (
            <label key={o.key} className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 accent-indigo-600"
                checked={q.data[o.key]}
                disabled={save.isPending}
                onChange={(e) =>
                  save.mutate(
                    { [o.key]: e.target.checked },
                    { onSuccess: () => toast.success("개인정보 설정을 저장했어요.") },
                  )
                }
              />
              <span>
                <span className="font-medium">{o.label}</span>
                <span className="mt-0.5 block text-xs text-slate-500">{o.hint}</span>
              </span>
            </label>
          ))}
      </CardBody>
    </Card>
  );
}
