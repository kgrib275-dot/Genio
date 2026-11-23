// 사이드바 메뉴 정의: 역할마다 보이는 메뉴가 다르다(쓰기 · 만들기 · 팀 묶음).
import {
  LayoutGrid,
  MessagesSquare,
  ClipboardList,
  BookOpen,
  Table2,
  Plug,
  Store,
  Users,
  Shield,
  GraduationCap,
  BookMarked,
  type LucideIcon,
} from "lucide-react";
import { ko } from "@/i18n/ko";
import type { Role } from "@/lib/api/types";
import { canEdit, canManage } from "@/store/session";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  show?: (role: Role | null) => boolean;
  /** 화면 투어가 짚는 표시(data-tour) */
  tour?: string;
  /** 사이드바에서 묶이는 곳: 쓰기(모두) · 만들기(제작자 이상) · 팀(워크스페이스·관리) */
  group?: NavGroupId;
}

type NavGroupId = "use" | "make" | "team";

const GROUP_LABEL: Record<NavGroupId, string> = {
  use: "쓰기",
  make: "만들기",
  team: "팀",
};
export const NAV: NavItem[] = [
  { to: "/", label: ko.nav.dashboard, icon: LayoutGrid, end: true, group: "use" },
  { to: "/hub", label: "챗봇 모음", icon: MessagesSquare, group: "use" },
  { to: "/tasks", label: "작업함", icon: ClipboardList, group: "use" },
  // 만드는 사람(제작자 이상)만 보는 메뉴. 사용자·운영자에게는 숨긴다
  { to: "/knowledge", label: ko.nav.knowledge, icon: BookOpen, show: canEdit, group: "make" },
  { to: "/data", label: "데이터 표", icon: Table2, show: canEdit, group: "make" },
  { to: "/connectors", label: ko.nav.connectors, icon: Plug, show: canEdit, group: "make" },
  { to: "/market", label: ko.nav.market, icon: Store, show: canEdit, group: "make" },
  { to: "/workspace", label: ko.nav.workspace, icon: Users, group: "team" },
  { to: "/admin", label: "관리", icon: Shield, show: canManage, tour: "nav-admin", group: "team" },
];

/** 이 역할이 보는 메뉴를 묶음별로. 묶음이 하나뿐이면 묶음 이름은 붙이지 않는다. */
export function navGroups(
  role: Role | null,
): { id: NavGroupId; label: string; items: NavItem[] }[] {
  const out: { id: NavGroupId; label: string; items: NavItem[] }[] = [];
  for (const id of ["use", "make", "team"] as const) {
    const items = NAV.filter((n) => n.group === id && (!n.show || n.show(role)));
    if (items.length > 0) out.push({ id, label: GROUP_LABEL[id], items });
  }
  return out;
}
export const BOTTOM_NAV: NavItem[] = [
  { to: "/learn", label: "배우기", icon: GraduationCap, tour: "nav-learn", show: canEdit },
  { to: "/help", label: "사용설명서", icon: BookMarked, tour: "nav-help" },
];
