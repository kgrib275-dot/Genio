import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ErrorBox } from "@/components/ErrorBox";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { toast } from "@/components/ui/toast-store";
import { api } from "@/lib/api/client";

type Level = "off" | "read" | "edit";

const OPTIONS: { value: Level; label: string; hint: string }[] = [
  { value: "off", label: "허용하지 않기", hint: "서비스 운영팀이 이 회사에 들어올 수 없어요." },
  {
    value: "read",
    label: "보기만 허용(기본)",
    hint: "문의를 도와주려고 화면을 볼 수 있어요. 아무것도 바꾸지 못해요.",
  },
  {
    value: "edit",
    label: "수정까지 허용",
    hint: "앱·지식·표를 같이 고쳐 줄 수 있어요. 멤버·연결 정보·AI 키·한도·보안 설정은 바꿀 수 없어요.",
  },
];

/** 서비스 운영팀(서비스 관리자)이 도와주러 들어오는 것을 어디까지 허용할지. 접속과 수정은 활동 기록에 남아요. */
export function SupportAccessCard({ ws }: { ws: string }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["security", ws],
    queryFn: () => api.get<{ support_access: Level }>(`/workspaces/${ws}/security`),
  });
  const save = useMutation({
    mutationFn: (v: Level) => api.put(`/workspaces/${ws}/security`, { support_access: v }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["security", ws] });
      toast.success("서비스 지원 접속 설정을 저장했어요.");
    },
  });
  const level = q.data?.support_access ?? "read";
  return (
    <Card>
      <CardHeader
        title="서비스 지원 접속"
        description="문의를 도와주러 서비스 운영팀이 이 회사에 들어오는 것을 정해요."
      />
      <CardBody className="space-y-3">
        <ErrorBox error={q.error ?? save.error} />
        {OPTIONS.map((o) => (
          <label key={o.value} className="flex items-start gap-2 text-sm">
            <input
              type="radio"
              name="support-access"
              className="mt-0.5 accent-indigo-600"
              checked={level === o.value}
              disabled={save.isPending || !q.data}
              onChange={() => save.mutate(o.value)}
            />
            <span>
              <span className="font-medium">{o.label}</span>
              <span className="mt-0.5 block text-xs text-slate-500">{o.hint}</span>
            </span>
          </label>
        ))}
        <p className="text-xs text-slate-500">
          들어온 기록은 &apos;활동 기록&apos;의 &apos;서비스 지원 접속&apos;에서 볼 수 있어요.
        </p>
      </CardBody>
    </Card>
  );
}
