"""모든 테이블 정의. 컬럼 삭제·이름 변경 금지(추가만)."""

import uuid
from datetime import UTC, datetime, timedelta
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
    event,
    func,
    select,
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
    # v0.3: 개인 설정(테마·글자 크기·기본 워크스페이스)
    preferences: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, server_default="{}")
    # v0.7 계정 스스로 관리: 이메일 인증 시각, 2단계 인증(TOTP 비밀값은 암호화), 복구 코드(해시),
    # 이 시각 이전에 발급한 토큰은 모두 무효(비밀번호 재설정·모든 기기에서 로그아웃)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    totp_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    recovery_codes: Mapped[list[str]] = mapped_column(JsonType, default=list, server_default="[]")
    tokens_valid_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuthToken(Base):
    """한 번 쓰는 링크 토큰(비밀번호 재설정·이메일 인증). 토큰 원문은 저장하지 않고 해시만 둔다."""

    __tablename__ = "auth_tokens"
    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # reset | verify
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()


class UserSession(Base):
    """로그인한 기기. 끊으면 그 기기의 토큰이 더 이상 통하지 않는다."""

    __tablename__ = "user_sessions"
    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    user_agent: Mapped[str] = mapped_column(String(300), default="", server_default="")
    ip: Mapped[str] = mapped_column(String(64), default="", server_default="")
    created_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    # v0.3: 프로젝트(없으면 워크스페이스 공용)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # v0.2: 앱 기능(App Toolkit)·환경 값(비밀은 value_enc에 암호화)
    features: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, server_default="{}")
    env_vars: Mapped[list[dict[str, Any]]] = mapped_column(
        JsonType, default=list, server_default="[]"
    )
    # v0.5: 저장해 둔 테스트 입력 [{name, input}]
    test_inputs: Mapped[list[dict[str, Any]]] = mapped_column(
        JsonType, default=list, server_default="[]"
    )


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
    # v0.5: 특정 사용자에게만(역할과 함께 쓰면 둘 중 하나만 맞아도 된다)
    allowed_users: Mapped[list[str]] = mapped_column(TextArray, default=list, server_default="{}")
    created_at: Mapped[datetime] = _created()
    # v0.4: 위젯 모양(색·위치·인사말 등)
    appearance: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, server_default="{}")


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
    # v0.2: 대화 값({{conv.x}})
    variables: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, server_default="{}")
    # v0.5: 상담원 전환 bot | handoff(사람 대기·응대 중) | closed
    status: Mapped[str] = mapped_column(String(20), default="bot", server_default="bot")
    assigned_to: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", name="conversations_assigned_to_fkey"), nullable=True
    )
    # v0.6: 기억 창보다 오래된 대화의 요약과, 요약에 들어간 마지막 메시지 시각
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    summary_upto: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    # v0.2: 피드백·주석·검열·출처·응답 시간
    feedback: Mapped[str | None] = mapped_column(String(10), nullable=True)
    feedback_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    annotation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    moderated: Mapped[bool] = mapped_column(default=False, server_default="false")
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JsonType, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # v0.3: 프로젝트(없으면 워크스페이스 공용)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # v0.2: 청킹·검색 설정
    settings: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, server_default="{}")
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
    # v0.2: 메타데이터·출처
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(
        "doc_metadata", JsonType, default=dict, server_default="{}"
    )
    source: Mapped[str] = mapped_column(String(20), default="upload", server_default="upload")
    url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # v0.5: 문서 단위 켜기·끄기(끄면 검색에서 빠짐)
    enabled: Mapped[bool] = mapped_column(default=True, server_default="true")


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
    # v0.2: 순서·켜고 끄기·부모 문단(부모-자식 청킹)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    enabled: Mapped[bool] = mapped_column(default=True, server_default="true")
    parent_content: Mapped[str | None] = mapped_column(Text, nullable=True)


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
    # v0.5: 측정 지표(첫 요청→검사 통과 시간, 수정 대화 수, 캔버스 직접 편집 수)
    metrics: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, server_default="{}")


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


# ---------- v0.2 ----------
class StoredFile(Base):
    """앱 입력·챗 첨부 파일."""

    __tablename__ = "files"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    app_id: Mapped[str | None] = mapped_column(
        ForeignKey("apps.id", ondelete="CASCADE"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(300))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _created()


class Annotation(Base):
    """주석 답변: 비슷한 질문이 오면 이 답을 바로 돌려준다."""

    __tablename__ = "annotations"
    id: Mapped[str] = _id()
    app_id: Mapped[str] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _created()


class AppApiKey(Base):
    """앱별 서비스 API 키. 원문은 만들 때 한 번만 보여 주고 해시만 저장한다."""

    __tablename__ = "app_api_keys"
    id: Mapped[str] = _id()
    app_id: Mapped[str] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(20))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _created()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # v0.5: 권한 범위 chat(대화) · run(흐름 실행) · logs(기록 읽기)
    scopes: Mapped[list[str]] = mapped_column(
        TextArray, default=lambda: ["chat", "run"], server_default="{chat,run}"
    )


class SystemSetting(Base):
    """인스턴스 전체 설정(회원가입 허용 등)."""

    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JsonType)


# ---------- v0.3 ----------
class Project(Base):
    """워크스페이스 안에서 앱·지식베이스를 묶는 단위. private이면 만든 사람·멤버(+소유자·관리자)만 본다."""

    __tablename__ = "projects"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    color: Mapped[str] = mapped_column(String(20), default="indigo", server_default="indigo")
    visibility: Mapped[str] = mapped_column(
        String(20), default="workspace", server_default="workspace"
    )
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _created()


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)
    id: Mapped[str] = _id()
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


# ---------- v0.4 자동 실행(외부에서 받기·예약)과 데이터 표 ----------
class AppTrigger(Base):
    """앱을 자동으로 실행하는 방법. kind=webhook(외부 호출) | schedule(예약)."""

    __tablename__ = "app_triggers"
    id: Mapped[str] = _id()
    app_id: Mapped[str] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100), default="", server_default="")
    enabled: Mapped[bool] = mapped_column(default=True, server_default="true")
    # webhook 주소에 쓰는 비밀 토큰(예약은 없음)
    token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    # webhook: {mode: async|sync, version?}; schedule: {cron, timezone, input, version?}
    config: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict, server_default="{}")
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # v0.5: 웹훅 서명 검증용 비밀값(암호화), 최근 받은 값 미리 보기(최대 5개, 비밀 헤더 제외)
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_payloads: Mapped[list[dict[str, Any]]] = mapped_column(
        JsonType, default=list, server_default="[]"
    )
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _created()


class DataTable(Base):
    """워크스페이스 안의 작은 표(흐름이 값을 저장·조회). n8n Data Tables·Make Data store와 같은 역할."""

    __tablename__ = "data_tables"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL", name="data_tables_project_id_fkey"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    # [{key, label, type: text|number|boolean|date|json}]
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class DataRow(Base):
    __tablename__ = "data_rows"
    __table_args__ = (UniqueConstraint("table_id", "row_key"),)
    id: Mapped[str] = _id()
    table_id: Mapped[str] = mapped_column(
        ForeignKey("data_tables.id", ondelete="CASCADE"), index=True
    )
    # 값 찾기·덮어쓰기(upsert)에 쓰는 고유 키(없어도 됨)
    row_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# ---------- v0.5 사람에게 맡기는 작업(질문·배정) ----------
class HumanTask(Base):
    """흐름이 사람에게 묻거나(question) 일을 맡긴(assignment) 것. 끝나면 흐름이 이어진다."""

    __tablename__ = "human_tasks"
    id: Mapped[str] = _id()
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    app_id: Mapped[str] = mapped_column(ForeignKey("apps.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE", name="human_tasks_run_id_fkey"),
        nullable=True,
        index=True,
    )
    node_id: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(20))  # question | assignment | approval
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text, default="", server_default="")
    # 질문이면 받을 항목 [{key,label,type}]
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)
    assignee_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", name="human_tasks_assignee_fkey"), nullable=True, index=True
    )
    assignee_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="open", index=True
    )  # open|done|cancelled
    response: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    # 로그인 없이 여는 링크(이메일·슬랙으로 보냄)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", name="human_tasks_completed_by_fkey"), nullable=True
    )


class ErrorEvent(Base):
    """서버 오류 기록(운영 준비). 요청 본문·헤더·비밀값은 남기지 않는다. 30일 보관."""

    __tablename__ = "error_events"
    id: Mapped[str] = _id()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    # api(처리되지 않은 API 오류) | engine(실행 엔진 내부 오류) | worker
    source: Mapped[str] = mapped_column(String(20), default="api")
    # 어디서: 'POST /api/v1/apps/{app_id}/runs' 같은 경로 틀, 또는 엔진의 실행 id
    where: Mapped[str] = mapped_column(String(300), default="")
    error_type: Mapped[str] = mapped_column(String(120), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


# 대화 메시지는 저장 시각 순서가 곧 대화 순서다. 같은 순간(시계 해상도 안)에 저장되면 순서가
# 뒤바뀔 수 있어, 같은 대화의 직전 메시지보다 늘 뒤가 되게 맞춘다(대화 기억 순서 보장).
@event.listens_for(Message, "before_insert")
def _message_after_previous(_mapper: Any, connection: Any, target: Message) -> None:
    last = connection.execute(
        select(func.max(Message.created_at)).where(
            Message.conversation_id == target.conversation_id
        )
    ).scalar()
    now = target.created_at or utcnow()
    if last is not None:
        if last.tzinfo is None and now.tzinfo is not None:
            last = last.replace(tzinfo=now.tzinfo)
        if now <= last:
            now = last + timedelta(microseconds=1)
    target.created_at = now
