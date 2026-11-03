"""앱·버전 서비스: 생성(템플릿 포함), 검증 환경 구성, 버전 저장, 직렬화."""

import copy
import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.core.errors import AppError, not_found
from api.engine.validator import ValidationEnv, validate_graph
from api.market import service as market
from api.models import (
    App,
    ConnectorCredential,
    ConnectorDefinition,
    KnowledgeBase,
    WorkflowVersion,
)
from api.schemas.graph import ValidationResult, starter_graph
from nodes import registry


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (base or "app")[:60] + "-" + uuid.uuid4().hex[:6]


def validation_env(db: Session, workspace_id: str) -> ValidationEnv:
    market.ensure_market_nodes(db)
    builtin = {s.type for s in registry.all() if s.source == "builtin"}
    creds = db.execute(
        select(ConnectorCredential.id, ConnectorDefinition.key)
        .join(ConnectorDefinition, ConnectorDefinition.id == ConnectorCredential.definition_id)
        .where(ConnectorCredential.workspace_id == workspace_id)
    ).all()
    kbs = set(
        db.scalars(select(KnowledgeBase.id).where(KnowledgeBase.workspace_id == workspace_id))
    )
    connectors = {i.key for i in market.installed_items(db, workspace_id, "connector")}
    return ValidationEnv(
        registry=registry,
        allowed_types=builtin | market.market_node_types(db, workspace_id),
        credentials={c[0]: c[1] for c in creds},
        connectors=connectors,
        knowledge_bases=kbs,
    )


def validate_for_app(db: Session, app: App, graph: dict[str, Any]) -> ValidationResult:
    return validate_graph(graph, validation_env(db, app.workspace_id))


def latest_version(db: Session, app_id: str) -> WorkflowVersion | None:
    return db.scalar(
        select(WorkflowVersion)
        .where(WorkflowVersion.app_id == app_id)
        .order_by(WorkflowVersion.version.desc())
        .limit(1)
    )


def latest_versions(db: Session, app_ids: list[str]) -> dict[str, int]:
    if not app_ids:
        return {}
    rows = db.execute(
        select(WorkflowVersion.app_id, func.max(WorkflowVersion.version))
        .where(WorkflowVersion.app_id.in_(app_ids))
        .group_by(WorkflowVersion.app_id)
    ).all()
    return {r[0]: int(r[1]) for r in rows}


def fill_template(db: Session, workspace_id: str, graph: dict[str, Any]) -> dict[str, Any]:
    """템플릿 placeholder를 이 워크스페이스의 첫 연결 정보·지식베이스로 채운다(없으면 비워 둠)."""
    g = copy.deepcopy(graph)
    cred_by_key: dict[str, str] = {}
    for cid, key in db.execute(
        select(ConnectorCredential.id, ConnectorDefinition.key)
        .join(ConnectorDefinition, ConnectorDefinition.id == ConnectorCredential.definition_id)
        .where(ConnectorCredential.workspace_id == workspace_id)
        .order_by(ConnectorCredential.created_at)
    ).all():
        cred_by_key.setdefault(key, cid)
    first_kb = db.scalar(
        select(KnowledgeBase.id)
        .where(KnowledgeBase.workspace_id == workspace_id)
        .order_by(KnowledgeBase.created_at)
    )
    for node in g.get("nodes", []):
        data = node.get("data", {})
        if node.get("type") == "connector" and str(data.get("credential_id", "")).startswith(
            "{{credential"
        ):
            data["credential_id"] = cred_by_key.get(str(data.get("connector")), "")
        if node.get("type") == "knowledge_search" and str(data.get("kb_id", "")).startswith("{{kb"):
            data["kb_id"] = first_kb or ""
    return g


def create_app(
    db: Session,
    *,
    workspace_id: str,
    user_id: str,
    name: str,
    app_type: str,
    description: str,
    icon: str,
    template_key: str | None,
    project_id: str | None = None,
) -> App:
    graph = starter_graph()
    if template_key:
        tpl = next(
            (t for t in market.templates(db, workspace_id) if t["key"] == template_key), None
        )
        if tpl is None:
            raise AppError(404, "템플릿을 찾을 수 없어요.", "마켓에서 템플릿을 먼저 설치하세요.")
        graph = fill_template(db, workspace_id, tpl["graph"])
    app = App(
        workspace_id=workspace_id,
        name=name,
        slug=slugify(name),
        type=app_type,
        description=description,
        icon=icon or "🤖",
        status="draft",
        created_by=user_id,
        draft_graph=graph,
        project_id=project_id or None,
    )
    db.add(app)
    return app


def get_app(db: Session, app_id: str) -> App:
    app = db.get(App, app_id)
    if app is None:
        raise not_found("앱")
    return app


def save_version(
    db: Session, app: App, graph: dict[str, Any], note: str, user_id: str
) -> WorkflowVersion:
    result = validate_for_app(db, app, graph)
    if not result.valid:
        raise AppError(
            422,
            "흐름에 고칠 부분이 있어 저장하지 못했어요.",
            "빨간 테두리 노드를 눌러 오류를 고친 뒤 다시 저장하세요.",
            errors=[e.model_dump() for e in result.errors],
        )
    last = latest_version(db, app.id)
    version = WorkflowVersion(
        app_id=app.id,
        version=(last.version + 1) if last else 1,
        graph=graph,
        created_by=user_id,
        note=note,
    )
    db.add(version)
    app.draft_graph = graph
    return version


def app_dict(app: App, latest: int | None) -> dict[str, Any]:
    return {
        "id": app.id,
        "workspace_id": app.workspace_id,
        "name": app.name,
        "slug": app.slug,
        "type": app.type,
        "description": app.description,
        "icon": app.icon,
        "status": app.status,
        "created_by": app.created_by,
        "updated_at": app.updated_at,
        "latest_version": latest,
        "project_id": app.project_id,
    }


def app_detail(db: Session, app: App) -> dict[str, Any]:
    last = latest_version(db, app.id)
    from api.services.app_config import merged_features, public_env_vars

    return {
        **app_dict(app, last.version if last else None),
        "draft_graph": app.draft_graph or starter_graph(),
        "features": merged_features(app.features),
        "env_vars": public_env_vars(app.env_vars or []),
    }
