"""모든 테이블 정의. 컬럼 삭제·이름 변경 금지(추가만)."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.db import Base, JsonType, TextArray

EMBEDDING_DIM = 1536


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


def _id() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=new_id)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# ---------- 3-1 조직·권한 ----------
class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = _id()
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = _created()


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = _id()
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = _id()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id"),)
    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20))
    token: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------- 3-2 앱·워크플로우 ----------
class App(Base):
    __tablename__ = "apps"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(20), default="workflow")
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(40), default="🤖")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    # ADR 0002
    draft_graph: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("app_id", "version"),)
    id: Mapped[str] = _id()
    app_id: Mapped[str] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    graph: Mapped[dict[str, Any]] = mapped_column(JsonType)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _created()
    note: Mapped[str] = mapped_column(Text, default="")


class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[str] = _id()
    app_id: Mapped[str] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(20))
    public_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    access: Mapped[str] = mapped_column(String(20), default="workspace")
    allowed_roles: Mapped[list[str]] = mapped_column(TextArray, default=list)
    created_at: Mapped[datetime] = _created()


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = _id()
    app_id: Mapped[str] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_versions.id", ondelete="SET NULL"), nullable=True
    )
    trigger: Mapped[str] = mapped_column(String(20), default="test")
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    input: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    output: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal("0"))
    # ADR 0002
    created_at: Mapped[datetime] = _created()
    graph_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    approval: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class RunStep(Base):
    __tablename__ = "run_steps"
    id: Mapped[str] = _id()
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30))
    input: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    output: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    logs: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 실행 순서(같은 시각에 시작한 단계도 순서를 지키기 위해). 0003에서 추가
    seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = _id()
    app_id: Mapped[str] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"), index=True)
    deployment_id: Mapped[str | None] = mapped_column(
        ForeignKey("deployments.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    external_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = _created()


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = _id()
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()


# ---------- 3-3 지식베이스 ----------
class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    embedding_model: Mapped[str] = mapped_column(String(100))
    chunk_size: Mapped[int] = mapped_column(Integer, default=800)
    created_at: Mapped[datetime] = _created()


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = _id()
    kb_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(300))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    created_at: Mapped[datetime] = _created()
    # ADR 0002
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class Chunk(Base):
    __tablename__ = "chunks"
    # 설계서 §3-3: 코사인 거리 ivfflat 인덱스(PostgreSQL에서만)
    __table_args__ = (
        Index(
            "ix_chunks_embedding_ivfflat",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ).ddl_if(dialect="postgresql"),
    )
    id: Mapped[str] = _id()
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    kb_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM).with_variant(JSON(), "sqlite"), nullable=True
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JsonType, default=dict)


# ---------- 3-4 커넥터 ----------
class ConnectorDefinition(Base):
    __tablename__ = "connector_definitions"
    __table_args__ = (UniqueConstraint("key", "version"),)
    id: Mapped[str] = _id()
    key: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(20), default="market")
    manifest: Mapped[dict[str, Any]] = mapped_column(JsonType)


class ConnectorCredential(Base):
    __tablename__ = "connector_credentials"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    definition_id: Mapped[str] = mapped_column(ForeignKey("connector_definitions.id"))
    name: Mapped[str] = mapped_column(String(200))
    secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _created()


# ---------- 3-5 빌더 챗 ----------
class BuilderSession(Base):
    __tablename__ = "builder_sessions"
    id: Mapped[str] = _id()
    app_id: Mapped[str] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


class BuilderMessage(Base):
    __tablename__ = "builder_messages"
    id: Mapped[str] = _id()
    session_id: Mapped[str] = mapped_column(
        ForeignKey("builder_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    graph_patch: Mapped[dict[str, Any] | None] = mapped_column(JsonType, nullable=True)
    created_at: Mapped[datetime] = _created()


# ---------- 3-6 마켓 ----------
class MarketItem(Base):
    __tablename__ = "market_items"
    id: Mapped[str] = _id()
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    description_md: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str] = mapped_column(String(40))
    publisher: Mapped[str] = mapped_column(String(100), default="platform")
    price: Mapped[int] = mapped_column(Integer, default=0)
    manifest: Mapped[dict[str, Any]] = mapped_column(JsonType)
    bundle_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tags: Mapped[list[str]] = mapped_column(TextArray, default=list)
    installs: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()
    # ADR 0002
    bundle_path: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Installation(Base):
    __tablename__ = "installations"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[str] = mapped_column(ForeignKey("market_items.id"))
    version: Mapped[str] = mapped_column(String(40))
    installed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    installed_at: Mapped[datetime] = _created()
    status: Mapped[str] = mapped_column(String(20), default="installed")


class Purchase(Base):
    __tablename__ = "purchases"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    item_id: Mapped[str] = mapped_column(ForeignKey("market_items.id"))
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="mock_paid")
    created_at: Mapped[datetime] = _created()


# ---------- 3-7 공통 ----------
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = _created()


class LlmProvider(Base):
    __tablename__ = "llm_providers"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(100))
    api_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    default_model: Mapped[str] = mapped_column(String(100))
    is_default: Mapped[bool] = mapped_column(default=False)
