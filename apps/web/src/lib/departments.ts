// 부서별 시작 안내: 부서를 고르면 예시 요청과 템플릿이 그 부서 것으로 좁혀진다.
export interface Department {
  id: string;
  label: string;
  /** 말로 만들기 예시 문장 */
  examples: string[];
  /** 이 부서에 어울리는 템플릿 키 */
  templates: string[];
}

export const ALL_DEPARTMENT = "all";

export const DEPARTMENTS: Department[] = [
  {
    id: "hr",
    label: "인사·총무",
    examples: [
      "사내 규정 문서로 직원 질문에 답하는 챗봇을 만들어 줘",
      "휴가 신청을 받아 팀장 승인 후 신청자에게 알려 줘",
      "신규 입사자 질문에 답하는 온보딩 도우미를 만들어 줘",
    ],
    templates: ["biz_onboarding_qa", "tpl_faq_bot", "tpl_approval_mail", "tpl_parallel_broadcast"],
  },
  {
    id: "sales",
    label: "영업",
    examples: [
      "견적 요청에서 품목과 수량을 뽑아 담당자 승인 뒤 회신 메일을 보내 줘",
      "상담 신청이 오면 고객 목록에 저장하고 영업팀에 알려 줘",
      "고객 메일을 요약해서 다음에 할 일을 정리해 줘",
    ],
    templates: ["biz_quote_request", "tpl_lead_capture", "tpl_shopify_orders_mail"],
  },
  {
    id: "cs",
    label: "고객지원",
    examples: [
      "고객 문의 메일을 분류해서 담당자 슬랙으로 보내 줘",
      "자주 묻는 질문 문서로 답하는 고객 응대 챗봇을 만들어 줘",
      "고객 피드백을 모아서 제품팀에 전달해 줘",
    ],
    templates: [
      "biz_inquiry_assign",
      "tpl_inquiry_router",
      "tpl_inquiry_zendesk_slack",
      "tpl_feedback_to_linear",
      "tpl_parallel_translate_summary",
    ],
  },
  {
    id: "finance",
    label: "재무·구매",
    examples: [
      "계약서 파일을 올리면 핵심 조건과 위험한 조항을 정리해 줘",
      "주문이 들어오면 재고와 결제를 확인해서 담당자에게 알려 줘",
      "경비 신청을 받아 금액이 크면 팀장 승인을 받게 해 줘",
    ],
    templates: ["biz_contract_review", "tpl_parallel_order_check", "tpl_order_sms_notify"],
  },
  {
    id: "report",
    label: "보고·회의",
    examples: [
      "주간 보고 초안을 만들어서 승인 후 메일로 보내 줘",
      "회의 메모를 받아 할 일 목록으로 정리해 줘",
      "매일 아침 어제 처리한 일을 요약해서 사내 메신저로 보내 줘",
    ],
    templates: [
      "biz_weekly_report",
      "tpl_weekly_report_xlsx",
      "tpl_daily_report",
      "tpl_daily_digest_kr",
      "tpl_meeting_to_notion",
      "tpl_doc_summary",
      "tpl_chat_to_task",
    ],
  },
];

export function departmentById(id: string): Department | undefined {
  return DEPARTMENTS.find((d) => d.id === id);
}

/** 고른 부서에 맞는 템플릿만 남긴다('전체'이거나 모르는 부서면 그대로) */
export function filterTemplatesByDepartment<T extends { key: string }>(
  list: T[],
  departmentId: string,
): T[] {
  const dept = departmentById(departmentId);
  if (!dept) return list;
  const order = new Map(dept.templates.map((k, i) => [k, i]));
  return list
    .filter((t) => order.has(t.key))
    .sort((a, b) => (order.get(a.key) ?? 0) - (order.get(b.key) ?? 0));
}
