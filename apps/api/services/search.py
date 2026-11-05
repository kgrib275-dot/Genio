"""전체 검색창(Ctrl+K)용 검색(v0.8). 이 사용자의 역할이 볼 수 있는 것만 찾는다.

- 앱·프로젝트·지식베이스·데이터 표·연결 정보·마켓 아이템·화면(메뉴)을 한 번에 찾는다.
- 이 사람이 볼 수 없는 비공개 프로젝트 안의 항목은 존재도 드러내지 않는다.
- 연결 정보는 이름만 돌려주고 비밀값은 다루지 않는다.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from api.models import (
    App,
    ConnectorCredential,
    DataTable,
    Deployment,
    KnowledgeBase,
    MarketItem,
    Project,
)
from api.services.projects import hidden_project_ids

MAX_QUERY = 100
EDIT_ROLES = ("owner", "admin", "builder")
VIEW_ROLES = ("owner", "admin", "builder", "operator")
MANAGE_ROLES = ("owner", "admin")
ALL_ROLES = ("owner", "admin", "builder", "operator", "member")


@dataclass(frozen=True)
class PageEntry:
    title: str
    to: str
    subtitle: str
    keywords: tuple[str, ...]
    roles: tuple[str, ...]


# 화면(메뉴) 목록. 역할에 맞는 것만 보여 준다.
PAGES: tuple[PageEntry, ...] = (
    PageEntry(
        "대시보드", "/", "앱 목록·말로 만들기", ("홈", "메인", "dashboard", "새 앱"), ALL_ROLES
    ),
    PageEntry("작업함", "/tasks", "승인·질문·배정", ("승인", "할 일", "task", "inbox"), ALL_ROLES),
    PageEntry(
        "지식베이스", "/knowledge", "문서로 답하게 하기", ("문서", "rag", "knowledge"), VIEW_ROLES
    ),
    PageEntry(
        "데이터 표", "/data", "흐름이 기억할 값", ("표", "table", "csv", "데이터"), ALL_ROLES
    ),
    PageEntry(
        "연결 정보",
        "/connectors",
        "슬랙·메일 등 연결",
        ("커넥터", "connector", "키", "토큰"),
        EDIT_ROLES,
    ),
    PageEntry("마켓", "/market", "템플릿·커넥터 설치", ("market", "설치", "템플릿"), ALL_ROLES),
    PageEntry("워크스페이스", "/workspace", "멤버·사용량", ("멤버", "사용량", "비용"), ALL_ROLES),
    PageEntry(
        "프로젝트 현황", "/projects", "프로젝트 전체 보기", ("현황판", "프로젝트"), ALL_ROLES
    ),
    PageEntry("배우기", "/learn", "샘플과 강좌", ("강좌", "샘플", "처음", "튜토리얼"), ALL_ROLES),
    PageEntry("사용설명서", "/help", "쓰는 법", ("도움말", "help", "설명서"), ALL_ROLES),
    PageEntry(
        "내 설정",
        "/settings",
        "비밀번호·테마·보안",
        ("비밀번호", "테마", "2단계", "프로필"),
        ALL_ROLES,
    ),
    PageEntry(
        "공개 API 문서", "/api-docs", "API·MCP 사용법", ("api", "openapi", "swagger"), ALL_ROLES
    ),
    PageEntry("관리", "/admin", "소유자·관리자 화면", ("admin", "관리자"), MANAGE_ROLES),
    PageEntry(
        "관리 · AI 모델",
        "/admin?tab=llm",
        "AI 연결·모델",
        ("llm", "키", "openai", "claude"),
        MANAGE_ROLES,
    ),
    PageEntry(
        "관리 · 멤버", "/admin?tab=members", "계정 만들기·비밀번호", ("계정", "초대"), MANAGE_ROLES
    ),
    PageEntry(
        "관리 · 활동 기록",
        "/admin?tab=audit",
        "누가 무엇을 바꿨나",
        ("감사", "로그", "audit"),
        MANAGE_ROLES,
    ),
    PageEntry("관리 · API 키", "/admin?tab=keys", "앱 API 키 전체", ("api", "키"), MANAGE_ROLES),
    PageEntry(
        "관리 · 시스템 설정",
        "/admin?tab=system",
        "회원가입·메일",
        ("가입", "메일", "smtp"),
        MANAGE_ROLES,
    ),
)


def _like(text: str) -> str:
    esc = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


def _rank(title: str, q: str) -> tuple[int, int, str]:
    t = title.lower()
    ql = q.lower()
    return (0 if t.startswith(ql) else 1, t.find(ql) if ql in t else 999, t)


def _limit(stmt: Select[Any], n: int) -> Select[Any]:
    return stmt.limit(n * 3)  # 순위를 매긴 뒤 n개만 쓴다


def _pick(items: list[dict[str, Any]], q: str, n: int) -> list[dict[str, Any]]:
    return sorted(items, key=lambda i: _rank(str(i["title"]), q))[:n]


def search_pages(role: str, q: str, n: int) -> list[dict[str, Any]]:
    ql = q.lower()
    out = []
    for p in PAGES:
        if role not in p.roles:
            continue
        hay = " ".join((p.title, p.subtitle, *p.keywords)).lower()
        if not ql or ql in hay:
            out.append({"id": p.to, "title": p.title, "subtitle": p.subtitle, "to": p.to})
    return _pick(out, q, n) if q else out[:n]


def search_workspace(
    db: Session, ws: str, user_id: str, role: str, q: str, limit: int
) -> list[dict[str, Any]]:
    """그룹별 결과 목록. 빈 그룹은 빼고, 화면(메뉴)을 맨 앞에 둔다."""
    q = q.strip()[:MAX_QUERY]
    hidden = hidden_project_ids(db, ws, user_id, role)
    groups: list[dict[str, Any]] = []

    def add(kind: str, label: str, items: list[dict[str, Any]]) -> None:
        if items:
            groups.append({"kind": kind, "label": label, "items": items})

    add("pages", "화면", search_pages(role, q, limit if q else 30))  # 빈 검색어는 바로 가기 전체
    if not q:
        return groups  # 빈 검색어: 화면 바로 가기만(최근 항목은 브라우저가 기억한다)
    pat = _like(q)

    # 앱: 사용자 역할은 배포된(published) 앱만, 공유 화면으로 보낸다
    app_q = select(App).where(
        App.workspace_id == ws,
        or_(App.name.ilike(pat, escape="\\"), App.description.ilike(pat, escape="\\")),
    )
    if role == "member":
        app_q = app_q.where(App.status == "published")
    if hidden:
        app_q = app_q.where(or_(App.project_id.is_(None), App.project_id.not_in(hidden)))
    apps = list(db.scalars(_limit(app_q.order_by(App.updated_at.desc()), limit)))
    tokens: dict[str, str] = {}
    if role == "member" and apps:
        for dep in db.scalars(
            select(Deployment)
            .where(Deployment.app_id.in_([a.id for a in apps]))
            .order_by(Deployment.created_at.desc())
        ):
            tokens.setdefault(dep.app_id, dep.public_token)
    app_items = []
    for a in apps:
        if role in EDIT_ROLES:
            to = f"/apps/{a.id}/builder"
        elif role == "operator":
            to = f"/apps/{a.id}/runs"
        elif a.id in tokens:
            to = f"/share/{tokens[a.id]}"
        else:
            continue
        app_items.append(
            {
                "id": a.id,
                "title": a.name,
                "subtitle": (a.description or "").strip()[:80]
                or ("챗봇" if a.type == "chat" else "흐름"),
                "to": to,
                "icon": a.icon,
            }
        )
    add("apps", "앱", _pick(app_items, q, limit))

    projects = [
        {
            "id": p.id,
            "title": p.name,
            "subtitle": (p.description or "")[:80],
            "to": f"/projects?project={p.id}",
        }
        for p in db.scalars(
            _limit(
                select(Project).where(
                    Project.workspace_id == ws,
                    or_(
                        Project.name.ilike(pat, escape="\\"),
                        Project.description.ilike(pat, escape="\\"),
                    ),
                ),
                limit,
            )
        )
        if p.id not in hidden
    ]
    add("projects", "프로젝트", _pick(projects, q, limit))

    if role in VIEW_ROLES:
        kbs = [
            {"id": k.id, "title": k.name, "subtitle": "지식베이스", "to": "/knowledge"}
            for k in db.scalars(
                _limit(
                    select(KnowledgeBase).where(
                        KnowledgeBase.workspace_id == ws, KnowledgeBase.name.ilike(pat, escape="\\")
                    ),
                    limit,
                )
            )
            if k.project_id not in hidden
        ]
        add("knowledge", "지식베이스", _pick(kbs, q, limit))

    tables = [
        {
            "id": t.id,
            "title": t.name,
            "subtitle": (t.description or "데이터 표")[:80],
            "to": f"/data/{t.id}",
        }
        for t in db.scalars(
            _limit(
                select(DataTable).where(
                    DataTable.workspace_id == ws, DataTable.name.ilike(pat, escape="\\")
                ),
                limit,
            )
        )
        if t.project_id not in hidden
    ]
    add("tables", "데이터 표", _pick(tables, q, limit))

    if role in EDIT_ROLES:
        creds = [
            {"id": c.id, "title": c.name, "subtitle": "연결 정보", "to": "/connectors"}
            for c in db.scalars(
                _limit(
                    select(ConnectorCredential).where(
                        ConnectorCredential.workspace_id == ws,
                        ConnectorCredential.name.ilike(pat, escape="\\"),
                    ),
                    limit,
                )
            )
        ]
        add("connections", "연결 정보", _pick(creds, q, limit))

    market = [
        {"id": m.key, "title": m.name, "subtitle": (m.summary or "")[:80], "to": f"/market/{m.key}"}
        for m in db.scalars(
            _limit(
                select(MarketItem).where(
                    or_(
                        MarketItem.name.ilike(pat, escape="\\"),
                        MarketItem.summary.ilike(pat, escape="\\"),
                    )
                ),
                limit,
            )
        )
    ]
    add("market", "마켓", _pick(market, q, limit))
    return groups
