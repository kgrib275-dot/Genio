import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ErrorBox } from "@/components/ErrorBox";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { toast } from "@/components/ui/toast-store";
import { api } from "@/lib/api/client";

/** 외부 목록(공식 MCP 레지스트리)에서 서비스를 찾아 연결하는 기능을 이 회사에서 쓸지 정한다. 기본은 꺼짐. */
export function ExternalCatalogCard({ ws }: { ws: string }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["security", ws],
    queryFn: () => api.get<{ external_catalog: boolean }>(`/workspaces/${ws}/security`),
  });
  const save = useMutation({
    mutationFn: (v: boolean) => api.put(`/workspaces/${ws}/security`, { external_catalog: v }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["security", ws] });
      toast.success("외부 서비스 찾기 설정을 저장했어요.");
    },
  });
  const on = q.data?.external_catalog ?? false;
  return (
    <Card>
      <CardHeader
        title="외부 서비스 찾기"
        description="공식 MCP 목록에서 최신 서비스를 검색해 연결해요."
      />
      <CardBody className="space-y-2">
        <ErrorBox error={q.error ?? save.error} />
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-0.5 accent-indigo-600"
            checked={on}
            disabled={!q.data || save.isPending}
            onChange={(e) => save.mutate(e.target.checked)}
          />
          <span>
            <span className="font-medium">이 회사에서 쓰기</span>
            <span className="mt-0.5 block text-xs text-slate-500">
              켜면 제작자가 외부 목록을 검색할 수 있고, 소유자·관리자가 연결할 수 있어요. 목록은
              누구나 올릴 수 있으니 연결 전에 출처를 확인하세요. 검색과 연결은 활동 기록에 남아요.
            </span>
          </span>
        </label>
      </CardBody>
    </Card>
  );
}
