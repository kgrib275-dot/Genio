"""처음 쓰는 사람이 따라 해 볼 샘플 11가지('샘플 체험' 프로젝트). 배우기 강좌(화면 /learn)와 짝을 이룬다.

AI 키 없이 돌아가는 것 8개(모범 답변·승인·데이터 표·예약·외부에서 받기·외부 호출·코드·병렬 갈래)와
AI 키를 넣으면 돌아가는 것 3개(지식베이스 Q&A·문의 분류·회의록 요약)로 이뤄진다.
한 워크스페이스에 한 번만 넣는다(workspace.settings["samples_version"]).
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.core.errors import AppError
from api.core.security import random_token
from api.models import (
    Annotation,
    App,
    AppTrigger,
    DataRow,
    DataTable,
    Deployment,
    Document,
    KnowledgeBase,
    Project,
    Workspace,
)
from api.services import apps as app_svc
from api.services import triggers as trig_svc
from api.services.app_config import merged_features
from api.services.queue import enqueue_document

log = logging.getLogger("genio.samples")
# 2: ⑪ 병렬 갈래 샘플(v0.6)
SAMPLES_VERSION = 2
PROJECT_NAME = "샘플 체험"


def _n(nid: str, ntype: str, x: int, y: int, data: dict[str, Any]) -> dict[str, Any]:
    return {"id": nid, "type": ntype, "position": {"x": x, "y": y}, "data": data}


def _e(src: str, tgt: str, handle: str | None = None) -> dict[str, Any]:
    e: dict[str, Any] = {"id": f"e_{src}_{tgt}", "source": src, "target": tgt}
    if handle:
        e["sourceHandle"] = handle
        e["id"] = f"e_{src}_{handle}_{tgt}"
    return e


def _graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    return {"version": 1, "nodes": nodes, "edges": edges, "variables": {}}


def _field(key: str, label: str, ftype: str = "text", required: bool = False) -> dict[str, Any]:
    return {"key": key, "label": label, "type": ftype, "required": required}


def status(db: Session, ws_id: str) -> dict[str, Any]:
    ws = db.get(Workspace, ws_id)
    version = int((ws.settings or {}).get("samples_version") or 0) if ws else 0
    installed = version >= SAMPLES_VERSION
    project = db.scalar(
        select(Project).where(Project.workspace_id == ws_id, Project.name == PROJECT_NAME)
    )
    apps = (
        list(db.scalars(select(App).where(App.project_id == project.id)))
        if project is not None
        else []
    )
    return {
        "installed": installed,
        "project_id": project.id if project else None,
        "apps": [{"id": a.id, "name": a.name, "type": a.type} for a in apps],
    }


# ---------------- 데이터 ----------------
def _table(
    db: Session,
    ws_id: str,
    project_id: str,
    user_id: str,
    name: str,
    desc: str,
    columns: list[dict[str, Any]],
    rows: list[tuple[str | None, dict[str, Any]]],
) -> DataTable:
    t = DataTable(
        workspace_id=ws_id,
        project_id=project_id,
        name=name,
        description=desc,
        columns=columns,
        created_by=user_id,
    )
    db.add(t)
    db.flush()
    for key, data in rows:
        db.add(DataRow(table_id=t.id, row_key=key, data=data))
    return t


POLICY_DOCS = {
    "연차휴가 규정.md": """# 연차휴가 규정
- 입사 1년 미만: 한 달 개근할 때마다 1일, 최대 11일.
- 입사 1년 이상: 1년에 15일. 3년 이상 일하면 2년마다 1일씩 늘어 최대 25일.
- 반차(4시간)로 나눠 쓸 수 있어요.
- 신청: 사내 포털 > 휴가 신청. 팀장 승인 뒤 확정돼요. 3일 이상은 1주 전에 신청해 주세요.
- 남은 연차는 다음 해로 넘어가지 않고, 쓰지 못한 날은 연말에 수당으로 정산해요.
""",
    "출장비 규정.md": """# 출장비 규정
- 교통비: 실비. KTX는 일반실, 항공은 일반석.
- 숙박비: 서울 1박 12만 원, 그 밖 지역 10만 원까지.
- 식비: 하루 3만 원(일비 포함).
- 청구: 출장 뒤 7일 안에 영수증을 경비 시스템에 올려요. 법인카드를 썼다면 영수증만 붙이면 돼요.
""",
    "정보보안 수칙.md": """# 정보보안 수칙
- 비밀번호는 90일마다 바꾸고, 다른 서비스와 같은 비밀번호를 쓰지 않아요.
- 고객 개인정보는 사내 시스템 밖(개인 메일·메신저)으로 보내지 않아요.
- 자리를 비울 때는 화면을 잠가요(Windows+L).
- 수상한 메일의 첨부파일은 열지 말고 보안팀(security@example.com)에 전달해요.
""",
}


def install(db: Session, ws_id: str, user_id: str) -> dict[str, Any]:
    """샘플 11가지를 넣는다. 예전 버전이 있으면 새 샘플만 더하고, 최신이면 409."""
    ws = db.get(Workspace, ws_id)
    if ws is None:
        raise AppError(404, "워크스페이스를 찾을 수 없어요.", "목록에서 다시 골라 주세요.")
    if upgrade(db, ws_id, user_id):
        return status(db, ws_id)
    if (ws.settings or {}).get("samples_version"):
        raise AppError(
            409,
            "샘플은 이미 넣었어요.",
            "왼쪽 메뉴 프로젝트 > '샘플 체험'에서 확인하세요. 다시 넣으려면 그 프로젝트를 지운 뒤 시도하세요.",
        )
    project = Project(
        workspace_id=ws_id,
        name=PROJECT_NAME,
        description="처음 쓰는 사람이 따라 해 보는 샘플 11가지. 배우기 메뉴의 강좌와 짝을 이뤄요.",
        color="amber",
        visibility="workspace",
        created_by=user_id,
    )
    db.add(project)
    db.flush()
    pid = project.id

    customers = _table(
        db,
        ws_id,
        pid,
        user_id,
        "고객 명부",
        "샘플: 고객 정보를 저장·조회하는 표",
        [
            {"key": "name", "label": "이름", "type": "text"},
            {"key": "phone", "label": "연락처", "type": "text"},
            {"key": "grade", "label": "등급", "type": "text"},
            {"key": "memo", "label": "메모", "type": "text"},
        ],
        [
            (
                "010-1111-2222",
                {
                    "name": "김민지",
                    "phone": "010-1111-2222",
                    "grade": "VIP",
                    "memo": "분기마다 대량 주문",
                },
            ),
            (
                "010-2222-3333",
                {"name": "이도윤", "phone": "010-2222-3333", "grade": "일반", "memo": ""},
            ),
            (
                "010-3333-4444",
                {
                    "name": "박서준",
                    "phone": "010-3333-4444",
                    "grade": "일반",
                    "memo": "배송 전 전화 요청",
                },
            ),
            (
                "010-4444-5555",
                {
                    "name": "최하은",
                    "phone": "010-4444-5555",
                    "grade": "VIP",
                    "memo": "세금계산서 발행",
                },
            ),
            (
                "010-5555-6666",
                {
                    "name": "정우진",
                    "phone": "010-5555-6666",
                    "grade": "신규",
                    "memo": "첫 구매 쿠폰 사용",
                },
            ),
            (
                "010-6666-7777",
                {"name": "강지아", "phone": "010-6666-7777", "grade": "일반", "memo": ""},
            ),
            (
                "010-7777-8888",
                {"name": "윤태오", "phone": "010-7777-8888", "grade": "신규", "memo": ""},
            ),
            (
                "010-8888-9999",
                {
                    "name": "한소율",
                    "phone": "010-8888-9999",
                    "grade": "VIP",
                    "memo": "담당: 영업2팀",
                },
            ),
        ],
    )
    orders = _table(
        db,
        ws_id,
        pid,
        user_id,
        "주문",
        "샘플: 외부에서 받은 주문을 쌓는 표",
        [
            {"key": "product", "label": "상품", "type": "text"},
            {"key": "qty", "label": "수량", "type": "number"},
            {"key": "amount", "label": "금액", "type": "number"},
            {"key": "customer", "label": "주문자", "type": "text"},
            {"key": "status", "label": "상태", "type": "text"},
        ],
        [
            (
                None,
                {
                    "product": "무선 키보드",
                    "qty": 2,
                    "amount": 98000,
                    "customer": "김민지",
                    "status": "접수",
                },
            ),
            (
                None,
                {
                    "product": "27인치 모니터",
                    "qty": 1,
                    "amount": 289000,
                    "customer": "박서준",
                    "status": "접수",
                },
            ),
            (
                None,
                {
                    "product": "USB-C 허브",
                    "qty": 5,
                    "amount": 145000,
                    "customer": "최하은",
                    "status": "완료",
                },
            ),
            (
                None,
                {
                    "product": "노트북 거치대",
                    "qty": 3,
                    "amount": 87000,
                    "customer": "정우진",
                    "status": "접수",
                },
            ),
            (
                None,
                {
                    "product": "웹캠",
                    "qty": 1,
                    "amount": 59000,
                    "customer": "한소율",
                    "status": "완료",
                },
            ),
        ],
    )
    leaves = _table(
        db,
        ws_id,
        pid,
        user_id,
        "휴가 기록",
        "샘플: 승인된 휴가 신청이 쌓이는 표",
        [
            {"key": "content", "label": "신청 내용", "type": "text"},
            {"key": "start", "label": "시작일", "type": "text"},
            {"key": "days", "label": "일수", "type": "number"},
            {"key": "result", "label": "결과", "type": "text"},
        ],
        [(None, {"content": "가족 여행", "start": "2026-11-20", "days": 2, "result": "승인"})],
    )

    kb = KnowledgeBase(
        workspace_id=ws_id,
        project_id=pid,
        name="사내 규정(샘플)",
        embedding_model="text-embedding-3-small",
        chunk_size=500,
    )
    db.add(kb)
    db.flush()
    docs: list[Document] = []
    for filename, text in POLICY_DOCS.items():
        raw = text.encode("utf-8")
        d = Document(
            kb_id=kb.id,
            filename=filename,
            mime="text/markdown",
            size=len(raw),
            status="uploaded",
            content=raw,
        )
        db.add(d)
        docs.append(d)

    made: list[App] = []
    version_of: dict[str, str] = {}  # 앱 id → 샘플 버전 id

    def app(
        name: str,
        app_type: str,
        icon: str,
        desc: str,
        graph: dict[str, Any],
        features: dict[str, Any] | None = None,
        test_inputs: list[dict[str, Any]] | None = None,
    ) -> App:
        a = App(
            workspace_id=ws_id,
            name=name,
            slug=app_svc.slugify(name),
            type=app_type,
            description=desc,
            icon=icon,
            status="draft",
            created_by=user_id,
            draft_graph=graph,
            project_id=pid,
            features=merged_features(features or {}),
            test_inputs=test_inputs or [],
        )
        db.add(a)
        db.flush()
        v = app_svc.save_version(db, a, graph, "샘플", user_id)
        db.flush()
        a.status = "published"
        made.append(a)
        version_of[a.id] = v.id
        return a

    def deploy(
        a: App, channel: str = "share_link", appearance: dict[str, Any] | None = None
    ) -> None:
        db.add(
            Deployment(
                app_id=a.id,
                version_id=version_of[a.id],
                channel=channel,
                public_token=random_token(18),
                access="public",
                allowed_roles=[],
                allowed_users=[],
                appearance=appearance or {},
            )
        )

    # 1) 자주 묻는 질문 봇 — 모범 답변·시작 인사·추천 질문·상담원 연결(AI 키 없이)
    faq = app(
        "① 자주 묻는 질문 봇",
        "chat",
        "💬",
        "모범 답변으로 자주 묻는 질문에 바로 답하고, 못 풀면 상담원에게 넘겨요. AI 키 없이 돼요.",
        _graph(
            [
                _n(
                    "n1",
                    "input",
                    0,
                    0,
                    {"label": "질문 받기", "fields": [_field("message", "질문", required=True)]},
                ),
                _n(
                    "n2",
                    "output",
                    320,
                    0,
                    {
                        "label": "모르는 질문",
                        "template": "그 질문은 아직 배우지 못했어요. 아래 '상담원 연결'을 누르면 담당자가 이어서 도와드려요.",
                    },
                ),
            ],
            [_e("n1", "n2")],
        ),
        {
            "opening_statement": "안녕하세요! 사내 도우미예요. 연차·출장비·재택근무처럼 자주 묻는 질문에 바로 답해 드려요.",
            "suggested_questions": [
                "연차는 며칠이에요?",
                "출장비는 어떻게 청구해요?",
                "재택근무 신청은 어디서 해요?",
            ],
            "annotation_reply": {"enabled": True, "score_threshold": 0.6},
            "handoff": {
                "enabled": True,
                "keywords": ["상담원", "사람이랑", "직원 연결"],
                "message": "담당자를 연결해 드릴게요. 이어서 적으신 말도 함께 전달돼요.",
            },
        },
    )
    for q, a_ in [
        (
            "연차는 며칠이에요?",
            "입사 1년이 지나면 1년에 15일이에요. 1년 미만이면 한 달 개근할 때마다 1일씩 생겨요(최대 11일).",
        ),
        (
            "출장비는 어떻게 청구해요?",
            "출장 뒤 7일 안에 경비 시스템에 영수증을 올리면 돼요. 숙박은 서울 1박 12만 원까지예요.",
        ),
        (
            "재택근무 신청은 어디서 해요?",
            "사내 포털 > 근무 신청 > 재택근무에서 전날까지 신청하면 팀장 승인 뒤 확정돼요.",
        ),
        (
            "비밀번호를 잊어버렸어요",
            "로그인 화면의 '비밀번호 찾기' 또는 IT 지원(내선 1234)으로 연락하세요.",
        ),
        (
            "복지 포인트는 어디에 써요?",
            "복지몰에서 도서·운동·건강검진 등에 쓸 수 있고, 매년 1월에 100만 포인트가 들어와요.",
        ),
        (
            "회의실 예약은 어떻게 해요?",
            "그룹웨어 > 자원 예약에서 회의실과 시간을 고르면 돼요. 2주 뒤까지 예약할 수 있어요.",
        ),
    ]:
        db.add(Annotation(app_id=faq.id, question=q, answer=a_, hit_count=0, created_by=user_id))
    deploy(faq)
    deploy(
        faq,
        "web_widget",
        {
            "primary_color": "#0ea5e9",
            "position": "right",
            "launcher_text": "사내 도우미",
            "greeting": "궁금한 점을 물어보세요!",
            "title": "사내 도우미",
        },
    )

    # 2) 휴가 신청 챗봇 — 챗에서 흐름 실행 → 승인(링크) → 결과가 챗으로(AI 키 없이)
    leave = app(
        "② 휴가 신청 챗봇",
        "chat",
        "🏖️",
        "챗으로 휴가를 신청하면 관리자에게 승인 요청이 가고, 승인·반려 결과가 대화에 돌아와요.",
        _graph(
            [
                _n(
                    "n1",
                    "input",
                    0,
                    0,
                    {
                        "label": "신청 받기",
                        "fields": [
                            _field("message", "신청 내용", required=True),
                            _field("start", "시작일(예: 2026-12-01)", required=True),
                            _field("days", "일수", "number", True),
                        ],
                    },
                ),
                _n(
                    "n2",
                    "approval",
                    320,
                    0,
                    {
                        "label": "팀장 승인",
                        "message": "{{n1.message}} — {{n1.start}}부터 {{n1.days}}일 휴가 신청이에요. 승인할까요?",
                        "approver_roles": ["owner", "admin"],
                        "branch": True,
                    },
                ),
                _n(
                    "n3",
                    "data_table",
                    640,
                    -100,
                    {
                        "label": "휴가 기록 저장",
                        "table_id": leaves.id,
                        "operation": "insert",
                        "data": {
                            "content": "{{n1.message}}",
                            "start": "{{n1.start}}",
                            "days": "{{n1.days}}",
                            "result": "승인",
                        },
                    },
                ),
                _n(
                    "n4",
                    "output",
                    960,
                    -100,
                    {
                        "label": "승인 안내",
                        "template": "승인됐어요! {{n1.start}}부터 {{n1.days}}일 휴가가 등록됐어요. 승인 메모: {{n2.comment}}",
                    },
                ),
                _n(
                    "n5",
                    "output",
                    640,
                    120,
                    {"label": "반려 안내", "template": "반려됐어요. 사유: {{n2.comment}}"},
                ),
            ],
            [
                _e("n1", "n2"),
                _e("n2", "n3", "approved"),
                _e("n3", "n4"),
                _e("n2", "n5", "rejected"),
            ],
        ),
        {
            "opening_statement": "휴가 신청을 도와드려요. 위 칸에 시작일과 일수를 적고, 아래에 신청 내용을 보내 주세요."
        },
    )
    deploy(leave)

    # 3) 고객 명부 저장 — 입력 폼 → 데이터 표(덮어쓰기·개수)
    cust = app(
        "③ 고객 명부 저장",
        "workflow",
        "📇",
        "입력 폼에 고객 정보를 넣으면 '고객 명부' 표에 저장하고(같은 연락처면 고침) 전체 인원을 알려 줘요.",
        _graph(
            [
                _n(
                    "n1",
                    "input",
                    0,
                    0,
                    {
                        "label": "고객 정보",
                        "fields": [
                            _field("name", "이름", required=True),
                            _field("phone", "연락처", required=True),
                            _field("grade", "등급(VIP·일반·신규)"),
                            _field("memo", "메모"),
                        ],
                    },
                ),
                _n(
                    "n2",
                    "data_table",
                    320,
                    0,
                    {
                        "label": "명부에 저장",
                        "table_id": customers.id,
                        "operation": "upsert",
                        "row_key": "{{n1.phone}}",
                        "data": {
                            "name": "{{n1.name}}",
                            "phone": "{{n1.phone}}",
                            "grade": "{{n1.grade}}",
                            "memo": "{{n1.memo}}",
                        },
                    },
                ),
                _n(
                    "n3",
                    "data_table",
                    640,
                    0,
                    {"label": "인원 세기", "table_id": customers.id, "operation": "count"},
                ),
                _n(
                    "n4",
                    "output",
                    960,
                    0,
                    {
                        "label": "결과",
                        "template": "{{n1.name}} 님 정보를 저장했어요. 지금 고객 명부에는 {{n3.count}}명이 있어요.",
                    },
                ),
            ],
            [_e("n1", "n2"), _e("n2", "n3"), _e("n3", "n4")],
        ),
        test_inputs=[
            {
                "name": "새 고객",
                "input": {
                    "name": "오지호",
                    "phone": "010-9999-0000",
                    "grade": "신규",
                    "memo": "샘플 입력",
                },
            }
        ],
    )
    deploy(cust)

    # 4) 매일 아침 현황 보고 — 예약 실행(평일 9시) + 날짜·시간 + 데이터 표 집계
    report = app(
        "④ 매일 아침 현황 보고",
        "workflow",
        "⏰",
        "평일 아침 9시에 '주문' 표를 세어 오늘의 현황을 만들어요. 자동 실행 탭에서 예약을 볼 수 있어요.",
        _graph(
            [
                _n("n1", "input", 0, 0, {"label": "시작", "fields": [_field("memo", "덧붙일 말")]}),
                _n(
                    "n2",
                    "date_time",
                    300,
                    0,
                    {
                        "label": "오늘 날짜",
                        "operation": "now",
                        "format": "%Y-%m-%d",
                        "timezone": "Asia/Seoul",
                    },
                ),
                _n(
                    "n3",
                    "data_table",
                    600,
                    0,
                    {"label": "전체 주문 수", "table_id": orders.id, "operation": "count"},
                ),
                _n(
                    "n4",
                    "data_table",
                    900,
                    0,
                    {
                        "label": "처리 대기 주문",
                        "table_id": orders.id,
                        "operation": "find",
                        "filter": {"status": "접수"},
                        "limit": 50,
                    },
                ),
                _n(
                    "n5",
                    "output",
                    1200,
                    0,
                    {
                        "label": "아침 보고",
                        "template": "📋 {{n2.result}} 아침 현황\n- 전체 주문: {{n3.count}}건\n- 처리 대기(접수): {{n4.count}}건\n{{n1.memo}}",
                    },
                ),
            ],
            [_e("n1", "n2"), _e("n2", "n3"), _e("n3", "n4"), _e("n4", "n5")],
        ),
    )

    # 5) 주문 접수 — 외부에서 받기(웹훅) + 값 정리 + 데이터 표 추가
    order = app(
        "⑤ 주문 접수(외부에서 받기)",
        "workflow",
        "📦",
        "쇼핑몰 같은 바깥 서비스가 주소로 주문을 보내면 금액을 계산해 '주문' 표에 쌓아요.",
        _graph(
            [
                _n(
                    "n1",
                    "input",
                    0,
                    0,
                    {
                        "label": "주문 받기",
                        "fields": [
                            _field("product", "상품", required=True),
                            _field("qty", "수량", "number", True),
                            _field("price", "단가", "number", True),
                            _field("customer", "주문자"),
                        ],
                    },
                ),
                _n(
                    "n2",
                    "set_fields",
                    300,
                    0,
                    {
                        "label": "금액 계산",
                        "fields": [
                            {"key": "amount", "value": "{{ n1.qty * n1.price }}", "type": "number"},
                            {"key": "status", "value": "접수", "type": "text"},
                        ],
                    },
                ),
                _n(
                    "n3",
                    "data_table",
                    600,
                    0,
                    {
                        "label": "주문 표에 추가",
                        "table_id": orders.id,
                        "operation": "insert",
                        "data": {
                            "product": "{{n1.product}}",
                            "qty": "{{n1.qty}}",
                            "amount": "{{n2.amount}}",
                            "customer": "{{n1.customer}}",
                            "status": "{{n2.status}}",
                        },
                    },
                ),
                _n(
                    "n4",
                    "output",
                    900,
                    0,
                    {
                        "label": "받았다는 답",
                        "template": "주문을 받았어요: {{n1.product}} {{n1.qty}}개, 금액 {{n2.amount}}원",
                    },
                ),
            ],
            [_e("n1", "n2"), _e("n2", "n3"), _e("n3", "n4")],
        ),
        test_inputs=[
            {
                "name": "키보드 주문",
                "input": {"product": "무선 키보드", "qty": 2, "price": 49000, "customer": "김민지"},
            }
        ],
    )

    # 6) 환율 조회 — 외부 호출(HTTP)
    fx = app(
        "⑥ 환율 조회(외부 호출)",
        "workflow",
        "💱",
        "공개 환율 API를 불러 원화 환율을 알려 줘요. 외부 호출 단계와 결과 값 꺼내 쓰기를 익혀요.",
        _graph(
            [
                _n(
                    "n1",
                    "input",
                    0,
                    0,
                    {
                        "label": "통화 고르기",
                        "fields": [_field("currency", "통화(USD·EUR·JPY)", required=True)],
                    },
                ),
                _n(
                    "n2",
                    "http",
                    320,
                    0,
                    {
                        "label": "환율 가져오기",
                        "method": "GET",
                        "url": "https://api.frankfurter.dev/v1/latest?base={{n1.currency}}&symbols=KRW",
                    },
                ),
                _n(
                    "n3",
                    "output",
                    640,
                    0,
                    {
                        "label": "결과",
                        "template": "1 {{n1.currency}} = {{n2.body.rates.KRW}}원 ({{n2.body.date}} 기준, 유럽중앙은행 자료)",
                    },
                ),
            ],
            [_e("n1", "n2"), _e("n2", "n3")],
        ),
        test_inputs=[{"name": "달러", "input": {"currency": "USD"}}],
    )
    deploy(fx)

    # 7) 견적 계산기 — 코드(자바스크립트) + 조건 분기
    quote = app(
        "⑦ 견적 계산기(코드·조건)",
        "workflow",
        "🧮",
        "수량·단가·할인 코드로 견적을 계산하고(자바스크립트 코드 단계), 100만 원 이상이면 결재 안내로 갈라져요.",
        _graph(
            [
                _n(
                    "n1",
                    "input",
                    0,
                    0,
                    {
                        "label": "견적 입력",
                        "fields": [
                            _field("qty", "수량", "number", True),
                            _field("unit_price", "단가", "number", True),
                            _field("discount_code", "할인 코드(WELCOME10)"),
                        ],
                    },
                ),
                _n(
                    "n2",
                    "code",
                    300,
                    0,
                    {
                        "label": "견적 계산",
                        "language": "javascript",
                        "inputs": {
                            "qty": "{{n1.qty}}",
                            "unit": "{{n1.unit_price}}",
                            "code": "{{n1.discount_code}}",
                        },
                        "code": "const qty = Number(inputs.qty) || 0;\nconst unit = Number(inputs.unit) || 0;\nconst rate = String(inputs.code).trim().toUpperCase() === 'WELCOME10' ? 0.1 : 0;\nconst supply = qty * unit;\nconst discount = Math.round(supply * rate);\nconst vat = Math.round((supply - discount) * 0.1);\nresult = { supply, discount, vat, total: supply - discount + vat };",
                    },
                ),
                _n(
                    "n3",
                    "condition",
                    600,
                    0,
                    {
                        "label": "100만 원 이상?",
                        "cases": [{"id": "big", "when": "{{n2.total}} >= 1000000"}],
                        "else": "small",
                    },
                ),
                _n(
                    "n4",
                    "output",
                    900,
                    -100,
                    {
                        "label": "결재 필요",
                        "template": "견적 합계 {{n2.total}}원(공급가 {{n2.supply}}, 할인 {{n2.discount}}, 부가세 {{n2.vat}}).\n100만 원 이상이라 팀장 결재가 필요해요.",
                    },
                ),
                _n(
                    "n5",
                    "output",
                    900,
                    120,
                    {
                        "label": "바로 발행",
                        "template": "견적 합계 {{n2.total}}원(공급가 {{n2.supply}}, 할인 {{n2.discount}}, 부가세 {{n2.vat}}). 바로 발행할 수 있어요.",
                    },
                ),
            ],
            [_e("n1", "n2"), _e("n2", "n3"), _e("n3", "n4", "big"), _e("n3", "n5", "small")],
        ),
        test_inputs=[
            {"name": "작은 견적", "input": {"qty": 3, "unit_price": 45000, "discount_code": ""}},
            {
                "name": "큰 견적(할인)",
                "input": {"qty": 40, "unit_price": 30000, "discount_code": "WELCOME10"},
            },
        ],
    )
    deploy(quote)

    # 8) 사내 규정 Q&A — 지식베이스 + AI + 출처(AI 키 필요)
    qa = app(
        "⑧ 사내 규정 Q&A(AI 키 필요)",
        "chat",
        "📚",
        "'사내 규정' 지식베이스에서 찾아 AI가 출처와 함께 답해요. 관리 > AI 모델에서 키를 넣고, 지식베이스 문서를 다시 처리하면 돼요.",
        _graph(
            [
                _n(
                    "n1",
                    "input",
                    0,
                    0,
                    {"label": "질문 받기", "fields": [_field("message", "질문", required=True)]},
                ),
                _n(
                    "n2",
                    "knowledge_search",
                    300,
                    0,
                    {"label": "규정 찾기", "kb_id": kb.id, "query": "{{n1.message}}", "top_k": 4},
                ),
                _n(
                    "n3",
                    "llm",
                    600,
                    0,
                    {
                        "label": "답 만들기",
                        "provider": "default",
                        "system": "당신은 사내 규정 도우미예요. 주어진 자료에 있는 내용만으로 짧고 정확하게 답하고, 없으면 '규정에서 찾지 못했어요'라고 말하세요.",
                        "prompt": "질문: {{n1.message}}\n\n자료:\n{{n2.context}}",
                        "memory": True,
                    },
                ),
                _n("n4", "output", 900, 0, {"label": "답", "template": "{{n3.text}}"}),
            ],
            [_e("n1", "n2"), _e("n2", "n3"), _e("n3", "n4")],
        ),
        {
            "opening_statement": "사내 규정에 대해 물어보세요. 답에 근거 문서를 함께 보여 드려요.",
            "suggested_questions": [
                "3년 차 연차는 며칠이에요?",
                "부산 출장 숙박비 한도는?",
                "수상한 메일을 받으면 어떻게 해요?",
            ],
            "citations": {"enabled": True},
            "follow_up": {"enabled": True},
        },
    )
    deploy(qa)

    # 9) 고객 문의 분류·배정 — AI 분류 + 담당자 배정(작업함)(AI 키 필요)
    app(
        "⑨ 고객 문의 분류·배정(AI 키 필요)",
        "workflow",
        "🗂️",
        "AI가 문의를 결제·배송·기타로 나누고, 분류마다 담당 역할에게 일을 맡겨요(작업함에 생겨요).",
        _graph(
            [
                _n(
                    "n1",
                    "input",
                    0,
                    0,
                    {
                        "label": "문의 받기",
                        "fields": [
                            _field("customer", "고객명", required=True),
                            _field("message", "문의 내용", required=True),
                        ],
                    },
                ),
                _n(
                    "n2",
                    "question_classifier",
                    300,
                    0,
                    {
                        "label": "문의 분류",
                        "provider": "default",
                        "query": "{{n1.message}}",
                        "classes": [
                            {
                                "id": "billing",
                                "name": "결제·환불",
                                "description": "결제, 환불, 청구서, 카드",
                            },
                            {
                                "id": "delivery",
                                "name": "배송",
                                "description": "배송 지연, 주소 변경, 파손",
                            },
                            {"id": "other", "name": "기타", "description": "그 밖의 문의"},
                        ],
                    },
                ),
                _n(
                    "n3",
                    "assign_task",
                    640,
                    -160,
                    {
                        "label": "결제팀 배정",
                        "title": "[결제] {{n1.customer}} 님 문의",
                        "detail": "{{n1.message}}",
                        "assignee_role": "operator",
                        "due_hours": 24,
                    },
                ),
                _n(
                    "n4",
                    "assign_task",
                    640,
                    0,
                    {
                        "label": "배송팀 배정",
                        "title": "[배송] {{n1.customer}} 님 문의",
                        "detail": "{{n1.message}}",
                        "assignee_role": "operator",
                        "due_hours": 24,
                    },
                ),
                _n(
                    "n5",
                    "assign_task",
                    640,
                    160,
                    {
                        "label": "관리자 배정",
                        "title": "[기타] {{n1.customer}} 님 문의",
                        "detail": "{{n1.message}}",
                        "assignee_role": "admin",
                        "due_hours": 48,
                    },
                ),
                _n(
                    "n6",
                    "output",
                    980,
                    0,
                    {
                        "label": "처리 완료",
                        "template": "'{{n2.class_name}}' 문의로 분류해 담당자에게 넘겼고, 처리가 끝났어요.",
                    },
                ),
            ],
            [
                _e("n1", "n2"),
                _e("n2", "n3", "billing"),
                _e("n2", "n4", "delivery"),
                _e("n2", "n5", "other"),
                _e("n3", "n6"),
                _e("n4", "n6"),
                _e("n5", "n6"),
            ],
        ),
        test_inputs=[
            {
                "name": "환불 문의",
                "input": {"customer": "김민지", "message": "지난주 결제한 키보드 환불하고 싶어요"},
            }
        ],
    )

    # 10) 회의록 요약 — 파일 올리기 + 문서 읽기 + AI 요약(AI 키 필요)
    minutes = app(
        "⑩ 회의록 요약(AI 키 필요)",
        "workflow",
        "📝",
        "회의록 파일(DOCX·PDF·TXT)을 올리면 요약·결정 사항·할 일을 정리해 줘요.",
        _graph(
            [
                _n(
                    "n1",
                    "input",
                    0,
                    0,
                    {"label": "파일 받기", "fields": [_field("file", "회의록 파일", "file", True)]},
                ),
                _n(
                    "n2",
                    "document_extractor",
                    300,
                    0,
                    {"label": "문서 읽기", "file": "{{n1.file}}", "max_chars": 20000},
                ),
                _n(
                    "n3",
                    "llm",
                    600,
                    0,
                    {
                        "label": "요약하기",
                        "provider": "default",
                        "system": "당신은 회의록 정리 도우미예요. 한국어로 짧고 명확하게 정리하세요.",
                        "prompt": "다음 회의록을 아래 형식으로 정리해 주세요.\n## 한 줄 요약\n## 결정 사항\n## 할 일(담당·기한)\n\n{{n2.text}}",
                    },
                ),
                _n("n4", "output", 900, 0, {"label": "정리 결과", "template": "{{n3.text}}"}),
            ],
            [_e("n1", "n2"), _e("n2", "n3"), _e("n3", "n4")],
        ),
    )
    deploy(minutes)

    db.flush()
    # 자동 실행: ④ 평일 9시 예약, ⑤ 외부에서 받기(결과 기다리기)
    sched = AppTrigger(
        app_id=report.id,
        kind="schedule",
        name="평일 아침 9시",
        enabled=True,
        config=trig_svc.clean_config(
            "schedule",
            {
                "cron": "0 9 * * 1-5",
                "timezone": "Asia/Seoul",
                "input": {"memo": "오늘도 좋은 하루 보내세요!"},
            },
        ),
        created_by=user_id,
    )
    trig_svc.refresh_next_run(sched)
    db.add(sched)
    db.add(
        AppTrigger(
            app_id=order.id,
            kind="webhook",
            name="쇼핑몰 주문",
            enabled=True,
            token=trig_svc.new_token(),
            config=trig_svc.clean_config("webhook", {"mode": "sync"}),
            created_by=user_id,
        )
    )
    add_parallel_sample(db, ws_id, user_id, pid)
    ws.settings = {**(ws.settings or {}), "samples_version": SAMPLES_VERSION}
    db.commit()
    for d in docs:
        try:
            enqueue_document(d.id)  # AI 키가 없으면 '오류'로 남고, 키를 넣은 뒤 다시 처리하면 된다
        except Exception:
            log.warning("샘플 문서 처리 예약 실패(doc=%s)", d.id)
    return status(db, ws_id)


# ---------------- v0.6: ⑪ 병렬 갈래 ----------------
PARALLEL_SAMPLE = "⑪ 출장 준비 한 번에(병렬 갈래)"


def parallel_graph() -> dict[str, Any]:
    """입력 → [환율 조회 | 돌아오는 날 계산 | 체크리스트] 동시에 → 합치기 → 결과."""
    return _graph(
        [
            _n(
                "n1",
                "input",
                0,
                160,
                {
                    "label": "출장 정보",
                    "fields": [
                        _field("city", "도시", required=True),
                        _field("currency", "통화(USD·EUR·JPY)", required=True),
                        _field("start", "출발일(예: 2026-12-01)", required=True),
                        _field("days", "며칠", "number", required=True),
                    ],
                },
            ),
            _n(
                "fx",
                "http",
                340,
                0,
                {
                    "label": "환율 가져오기",
                    "method": "GET",
                    "url": "https://api.frankfurter.dev/v1/latest?base={{n1.currency}}&symbols=KRW",
                    "_on_error": "default",
                    "_default": {"body": {"rates": {"KRW": "(못 가져옴)"}}},
                },
            ),
            _n(
                "back",
                "date_time",
                340,
                160,
                {
                    "label": "돌아오는 날",
                    "operation": "add",
                    "value": "{{n1.start}}",
                    "amount": "{{n1.days}}",
                    "unit": "days",
                    "format": "korean",
                },
            ),
            _n(
                "list",
                "template",
                340,
                320,
                {
                    "label": "체크리스트",
                    "template": "여권·충전기·{{n1.city}} 날씨에 맞는 옷·법인카드·출장 신청서",
                },
            ),
            _n(
                "join",
                "template",
                680,
                160,
                {
                    "label": "합치기",
                    "template": (
                        "{{n1.city}} 출장 준비\n"
                        "- 환율: 1 {{n1.currency}} = {{fx.body.rates.KRW}}원\n"
                        "- 돌아오는 날: {{back.result}}\n"
                        "- 챙길 것: {{list.output}}"
                    ),
                },
            ),
            _n("out", "output", 1000, 160, {"label": "결과", "template": "{{join.output}}"}),
        ],
        [
            _e("n1", "fx"),
            _e("n1", "back"),
            _e("n1", "list"),
            _e("fx", "join"),
            _e("back", "join"),
            _e("list", "join"),
            _e("join", "out"),
        ],
    )


def add_parallel_sample(db: Session, ws_id: str, user_id: str, project_id: str) -> App:
    graph = parallel_graph()
    a = App(
        workspace_id=ws_id,
        name=PARALLEL_SAMPLE,
        slug=app_svc.slugify(PARALLEL_SAMPLE),
        type="workflow",
        description=(
            "한 단계에서 세 갈래(환율 조회·날짜 계산·체크리스트)로 나가 동시에 실행하고, "
            "합치는 단계가 세 갈래를 모두 기다렸다가 한 번에 정리해요. AI 키 없이 동작해요."
        ),
        icon="🧳",
        status="draft",
        created_by=user_id,
        draft_graph=graph,
        project_id=project_id,
        features=merged_features({}),
        test_inputs=[
            {
                "name": "도쿄 3일",
                "input": {"city": "도쿄", "currency": "JPY", "start": "2026-12-01", "days": 3},
            }
        ],
    )
    db.add(a)
    db.flush()
    v = app_svc.save_version(db, a, graph, "샘플", user_id)
    db.flush()
    a.status = "published"
    db.add(
        Deployment(
            app_id=a.id,
            version_id=v.id,
            channel="share_link",
            public_token=random_token(18),
            access="public",
            allowed_roles=[],
            allowed_users=[],
            appearance={},
        )
    )
    return a


def upgrade(db: Session, ws_id: str, user_id: str) -> bool:
    """예전 버전 샘플이 들어 있는 워크스페이스에 새 샘플만 더한다(⑪)."""
    ws = db.get(Workspace, ws_id)
    if ws is None:
        return False
    current = int((ws.settings or {}).get("samples_version") or 0)
    if current == 0 or current >= SAMPLES_VERSION:
        return False
    project = db.scalar(
        select(Project).where(Project.workspace_id == ws_id, Project.name == PROJECT_NAME)
    )
    if project is None:
        return False
    exists = db.scalar(select(App).where(App.project_id == project.id, App.name == PARALLEL_SAMPLE))
    if exists is None:
        add_parallel_sample(db, ws_id, user_id, project.id)
    ws.settings = {**(ws.settings or {}), "samples_version": SAMPLES_VERSION}
    db.commit()
    return True
