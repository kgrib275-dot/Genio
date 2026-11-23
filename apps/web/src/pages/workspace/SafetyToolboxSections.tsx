// sections.tsx에서 분리한 구간: SafetyToolboxSections
import { BuilderRulesCard } from "@/pages/workspace/BuilderRulesCard";
import { DependenciesCard } from "@/pages/workspace/DependenciesCard";
import { NodePolicyCard } from "@/pages/workspace/NodePolicyCard";
import { AdminTwoFactorCard } from "@/pages/workspace/AdminTwoFactorCard";
import { ExternalCatalogCard } from "@/pages/workspace/ExternalCatalogCard";
import { SupportAccessCard } from "@/pages/workspace/SupportAccessCard";
import { ExportCard } from "@/pages/workspace/ExportCard";
import { PrivacyCard } from "@/pages/workspace/PrivacyCard";
import { SkillsCard } from "@/pages/workspace/SkillsCard";
import { canEdit, useSession } from "@/store/session";

/** 안전·규칙: 개인정보 가리기, 쓸 수 있는 단계 제한, 빌더 상시 규칙(소유자·관리자) */
export function SafetySection({ ws }: { ws: string }) {
  const role = useSession((s) => s.role);
  const admin = role === "owner" || role === "admin";
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-500">
        우리 팀이 앱을 안전하게 만들고 쓰도록 정하는 규칙이에요. 바꾸면 이 워크스페이스의 모든 앱에
        적용돼요.
      </p>
      {admin ? (
        <div className="grid gap-6 lg:grid-cols-2">
          <PrivacyCard ws={ws} />
          <AdminTwoFactorCard ws={ws} />
          <SupportAccessCard ws={ws} />
          <ExternalCatalogCard ws={ws} />
          <ExportCard ws={ws} />
          <NodePolicyCard ws={ws} />
          <BuilderRulesCard ws={ws} />
        </div>
      ) : (
        <p className="text-sm text-slate-500">소유자·관리자만 바꿀 수 있어요.</p>
      )}
    </div>
  );
}

/** 업무 요령·관계도: 스킬 관리와 '무엇을 어디서 쓰는지' 지도(제작자 이상) */
export function ToolboxSection({ ws }: { ws: string }) {
  const role = useSession((s) => s.role);
  if (!canEdit(role)) return <p className="text-sm text-slate-500">제작자 이상만 볼 수 있어요.</p>;
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-500">
        에이전트가 따를 업무 요령을 모아 두고, 어떤 앱이 어떤 연결 정보·지식을 쓰는지 한눈에 봐요.
      </p>
      <div className="grid gap-6 lg:grid-cols-2">
        <SkillsCard ws={ws} />
        <DependenciesCard ws={ws} />
      </div>
    </div>
  );
}
