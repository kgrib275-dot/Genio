// 배포 IP 접근 제한 편집: 허용한 IP·대역에서 온 요청만 이 주소를 열 수 있다.
import { Crosshair, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { fetchMyIp, useUpdateDeploymentIps, type DeploymentWithIps } from "@/lib/api/ipAccess";
import { badIpEntries, parseIpText } from "@/lib/ipRule";

export function IpEditor({
  appId,
  dep,
  onClose,
}: {
  appId: string;
  dep: DeploymentWithIps;
  onClose: () => void;
}) {
  const update = useUpdateDeploymentIps(appId);
  const [text, setText] = useState((dep.allowed_ips ?? []).join("\n"));
  const [myIp, setMyIp] = useState<string | null>(null);
  const entries = parseIpText(text);
  const bad = badIpEntries(entries);
  const tooMany = entries.length > 50;
  const mineIncluded = myIp ? entries.includes(myIp) : null;

  async function addMine() {
    try {
      const { ip } = await fetchMyIp();
      setMyIp(ip);
      if (!parseIpText(text).includes(ip)) setText((t) => (t.trim() ? `${t.trim()}\n${ip}` : ip));
    } catch (err) {
      toast.error(err);
    }
  }

  const save = (list: string[]) =>
    update.mutate(
      { id: dep.id, allowed_ips: list },
      {
        onSuccess: (d) => {
          toast.success(
            (d.allowed_ips ?? []).length
              ? `허용 주소 ${(d.allowed_ips ?? []).length}개로 제한했어요.`
              : "IP 제한을 풀었어요.",
          );
          onClose();
        },
      },
    );

  return (
    <div className="mt-3 space-y-3 rounded-md bg-slate-50 p-3" aria-label="IP 접근 제한">
      <div className="flex items-start gap-2 text-sm text-slate-600">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-indigo-500" aria-hidden />
        <p>
          허용한 주소에서 온 요청만 이 배포를 열 수 있어요(공유 화면·챗·실행·파일·위젯 모두).
          <b> 비워 두면 제한이 없어요.</b> 회사 내부망처럼 정해진 곳에서만 쓰게 하고 싶을 때 쓰세요.
        </p>
      </div>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-slate-600">
          허용할 IP·대역(한 줄에 하나)
        </span>
        <Textarea
          rows={4}
          aria-label="허용할 IP·대역"
          className="font-mono text-xs"
          placeholder={"203.0.113.7\n203.0.113.0/24\n2001:db8::/32"}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      <p className="text-xs text-slate-500">
        예: <code>203.0.113.7</code>(한 대), <code>203.0.113.0/24</code>(대역), IPv6도 돼요. 최대
        50개.
      </p>
      {bad.length > 0 && (
        <p role="alert" className="text-xs text-red-600">
          올바른 IP가 아니에요: {bad.slice(0, 3).join(", ")}
          {bad.length > 3 ? ` 외 ${bad.length - 3}개` : ""}. 예처럼 숫자와 점(또는 콜론)으로 적어
          주세요.
        </p>
      )}
      {tooMany && (
        <p role="alert" className="text-xs text-red-600">
          허용 주소는 50개까지예요. 넓은 대역(CIDR) 하나로 묶어 주세요.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" onClick={() => void addMine()}>
          <Crosshair className="h-3.5 w-3.5" /> 내 IP 추가
        </Button>
        {myIp && (
          <span className="text-xs text-slate-500">
            지금 내 IP: <code>{myIp}</code>
            {mineIncluded === false && " (목록에 없어요)"}
          </span>
        )}
      </div>
      {entries.length > 0 && myIp !== null && mineIncluded === false && (
        <p className="text-xs text-amber-700">
          내 IP가 목록에 없어요. 이대로 저장하면 나도 이 링크를 열 수 없어요(앱 만들기 화면은 그대로
          써요).
        </p>
      )}
      <ErrorBox error={update.error} />
      <div className="flex flex-wrap justify-end gap-2">
        {(dep.allowed_ips ?? []).length > 0 && (
          <Button
            size="sm"
            variant="ghost"
            className="mr-auto text-red-600"
            disabled={update.isPending}
            onClick={() => save([])}
          >
            제한 풀기
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={onClose}>
          취소
        </Button>
        <Button
          size="sm"
          disabled={update.isPending || bad.length > 0 || tooMany}
          onClick={() => save(entries)}
        >
          {entries.length === 0 ? "제한 없이 저장" : "저장"}
        </Button>
      </div>
    </div>
  );
}
