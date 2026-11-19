import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { api } from "@/lib/api/client";
import type { Member } from "@/lib/api/types";
import { ko } from "@/i18n/ko";

interface Assets {
  apps: { id: string; name: string; status: string }[];
  api_keys: number;
  triggers: number;
  data_tables: number;
  credentials: number;
}

/** 퇴사·이동하는 사람이 만든 앱·키·예약·표를 다른 멤버에게 넘기는 창 */
export function TransferAssetsDialog({
  ws,
  from,
  members,
  onClose,
}: {
  ws: string;
  from: Member;
  members: Member[];
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const assets = useQuery({
    queryKey: ["member-assets", ws, from.user_id],
    queryFn: () => api.get<Assets>(`/workspaces/${ws}/members/${from.user_id}/assets`),
  });
  const candidates = members.filter(
    (m) => m.user_id !== from.user_id && ["owner", "admin", "builder"].includes(m.role),
  );
  const [to, setTo] = useState("");
  const move = useMutation({
    mutationFn: () =>
      api.post<Record<string, number>>(`/workspaces/${ws}/members/${from.user_id}/transfer`, {
        to_user_id: to,
      }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["member-assets", ws] });
      void qc.invalidateQueries({ queryKey: ["apps"] });
      toast.success(`앱 ${r.apps ?? 0}개와 딸린 키·예약·표를 넘겼어요.`);
      onClose();
    },
    onError: (err) => toast.error(err),
  });
  const a = assets.data;
  const nothing =
    a && a.apps.length + a.data_tables + a.credentials === 0 && a.api_keys + a.triggers === 0;

  return (
    <Dialog
      open
      onClose={onClose}
      title={`${from.name}님이 만든 것 넘기기`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            닫기
          </Button>
          <Button
            disabled={!to || move.isPending || Boolean(nothing)}
            onClick={() => move.mutate()}
          >
            {move.isPending ? "넘기는 중…" : "넘기기"}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        {assets.isLoading && <Loading />}
        <ErrorBox error={assets.error} />
        {a && (
          <div className="rounded-lg bg-slate-50 p-3">
            {nothing ? (
              <p className="text-slate-600">넘길 것이 없어요. 이 사람이 만든 앱·표가 없어요.</p>
            ) : (
              <>
                <p className="font-medium text-slate-800">
                  앱 {a.apps.length}개 · API 키 {a.api_keys}개 · 자동 실행 {a.triggers}개 · 데이터
                  표 {a.data_tables}개 · 연결 정보 {a.credentials}개
                </p>
                {a.apps.length > 0 && (
                  <ul className="mt-1 list-disc pl-5 text-slate-600">
                    {a.apps.slice(0, 8).map((x) => (
                      <li key={x.id}>{x.name}</li>
                    ))}
                    {a.apps.length > 8 && <li>…외 {a.apps.length - 8}개</li>}
                  </ul>
                )}
              </>
            )}
          </div>
        )}
        <Field
          label="받을 사람"
          htmlFor="transfer-to"
          hint="앱을 만들 수 있는 역할(제작자 이상)만 나와요."
        >
          <Select id="transfer-to" value={to} onChange={(e) => setTo(e.target.value)}>
            <option value="">고르세요</option>
            {candidates.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.name} ({ko.roles[m.role]})
              </option>
            ))}
          </Select>
        </Field>
        <p className="text-xs text-slate-500">
          넘기면 만든 사람 표시가 바뀌고, 앱에 딸린 키·자동 실행도 받는 사람 것이 돼요. 되돌리려면
          받은 사람이 다시 넘겨야 해요.
        </p>
      </div>
    </Dialog>
  );
}
