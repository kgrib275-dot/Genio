import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ErrorBox } from "@/components/ErrorBox";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { toast } from "@/components/ui/toast-store";
import { api } from "@/lib/api/client";

interface Security {
  require_admin_2fa: boolean;
  without_2fa: string[];
}

/** 관리자는 2단계 인증 필수(선택). 켜도 로그인·보기는 그대로고, 연결 정보·AI 키 변경만 막혀요. */
export function AdminTwoFactorCard({ ws }: { ws: string }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["security", ws],
    queryFn: () => api.get<Security>(`/workspaces/${ws}/security`),
  });
  const save = useMutation({
    mutationFn: (v: boolean) =>
      api.put<Security>(`/workspaces/${ws}/security`, { require_admin_2fa: v }),
    onSuccess: (d) => {
      qc.setQueryData(["security", ws], d);
      toast.success(d.require_admin_2fa ? "관리자 2단계 인증을 필수로 했어요." : "필수를 껐어요.");
    },
  });
  const d = q.data;
  return (
    <Card>
      <CardHeader
        title="관리자 2단계 인증"
        description="계정이 털려도 연결 정보와 AI 키는 지킬 수 있게 해 줘요."
      />
      <CardBody className="space-y-3">
        <ErrorBox error={q.error ?? save.error} />
        {d && (
          <>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 accent-indigo-600"
                checked={d.require_admin_2fa}
                disabled={save.isPending}
                onChange={(e) => save.mutate(e.target.checked)}
              />
              <span>
                <span className="font-medium">소유자·관리자는 2단계 인증을 써야 해요</span>
                <span className="mt-0.5 block text-xs text-slate-500">
                  켜도 로그인과 화면 보기는 그대로예요. 2단계 인증을 안 쓰는 관리자는 연결 정보·AI
                  키를 바꿀 때만 막혀요.
                </span>
              </span>
            </label>
            {d.without_2fa.length > 0 && (
              <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
                아직 2단계 인증을 안 쓰는 관리자: {d.without_2fa.join(", ")}.{" "}
                <Link to="/settings" className="underline">
                  내 계정에서 켜기
                </Link>
              </p>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
