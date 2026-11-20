import { Shield } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { PageContainer } from "@/app/Layout";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { HelpButton } from "@/help/HelpButton";
import { ko } from "@/i18n/ko";
import {
  LlmSection,
  MembersSection,
  ToolboxSection,
  UsageSection,
} from "@/pages/workspace/sections";
import { canEdit, canManage, canViewRuns, useSession } from "@/store/session";

type Tab = "members" | "llm" | "usage" | "toolbox";

/** 모든 역할이 보는 워크스페이스 정보. 바꾸는 일은 '관리'(소유자·관리자)에서 한다. */
export default function WorkspacePage() {
  const { workspaceId: ws, role } = useSession();
  const manage = canManage(role);
  // 소유자·관리자는 같은 탭이 '관리'에 있어서(바꿀 수 있는 곳) 여기서는 멤버만 보여 헷갈리지 않게 한다
  const tabs: { value: Tab; label: string }[] = manage
    ? [{ value: "members", label: "멤버" }]
    : [
        { value: "members", label: "멤버" },
        ...(canEdit(role) ? [{ value: "llm" as Tab, label: "AI 모델" }] : []),
        ...(canViewRuns(role) ? [{ value: "usage" as Tab, label: "사용량" }] : []),
        ...(canEdit(role) ? [{ value: "toolbox" as Tab, label: "업무 요령·관계도" }] : []),
      ];
  const [tab, setTab] = useState<Tab>("members");

  return (
    <PageContainer>
      <PageHeader
        title="워크스페이스"
        description="멤버와 내 역할, AI 연결, 사용량을 봐요."
        help={<HelpButton page="workspace" />}
      />
      <Card className="mb-6 flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
        <span className="text-slate-500">내 역할</span>
        <span className="font-semibold">{role ? ko.roles[role] : "-"}</span>
        {manage && (
          <Link
            to="/admin"
            className="ml-auto inline-flex items-center gap-1 font-medium text-indigo-600 hover:underline"
          >
            <Shield className="h-4 w-4" /> AI 모델·사용량·업무 요령은 관리에서
          </Link>
        )}
      </Card>
      <Tabs value={tab} onChange={setTab} items={tabs} />
      {tab === "members" && <MembersSection ws={ws} manage={false} />}
      {tab === "llm" && <LlmSection ws={ws} manage={false} />}
      {tab === "usage" && <UsageSection ws={ws} />}
      {tab === "toolbox" && <ToolboxSection ws={ws} />}
    </PageContainer>
  );
}
