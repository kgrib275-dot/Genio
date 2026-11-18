// 후속(Z2): 쓸 수 있는 단계 제한 — 체크한 단계는 이 워크스페이스에서 쓰지 못하게 막는다
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { toast } from "@/components/ui/toast-store";
import { useNodePolicy, useSaveNodePolicy } from "@/lib/api/nodePolicy";

export function NodePolicyCard({ ws }: { ws: string }) {
  const q = useNodePolicy(ws);
  const save = useSaveNodePolicy(ws);
  const blocked = new Set(q.data?.blocked_types ?? []);
  const toggle = (type: string, on: boolean) => {
    const next = new Set(blocked);
    if (on) next.add(type);
    else next.delete(type);
    save.mutate([...next], { onSuccess: () => toast.success("쓸 수 있는 단계를 저장했어요.") });
  };
  return (
    <Card>
      <CardHeader
        title="쓸 수 없게 막을 단계"
        description="체크한 단계는 이 워크스페이스의 새 흐름에서 쓰지 못해요. 빌더도 그 단계를 쓰지 않고, 시험 실행·버전 저장 때 오류로 알려요. 이미 배포된 버전은 그대로 돌아요."
      />
      <CardBody className="space-y-2">
        {q.isLoading && <Loading />}
        <ErrorBox error={q.error ?? save.error} />
        <div className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
          {(q.data?.node_types ?? [])
            .filter((n) => !n.locked)
            .map((n) => (
              <label key={n.type} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="accent-red-600"
                  checked={blocked.has(n.type)}
                  disabled={save.isPending}
                  onChange={(e) => toggle(n.type, e.target.checked)}
                />
                <span>{n.label}</span>
                <span className="text-xs text-slate-400">{n.category}</span>
              </label>
            ))}
        </div>
      </CardBody>
    </Card>
  );
}
