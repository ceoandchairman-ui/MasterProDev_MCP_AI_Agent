"""Relational schema. Sensitive fields are stored encrypted with keyed blind indexes for lookup."""

import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

EMBEDDING_DIM = 1024  # BAAI/bge-m3


class EmbeddingType(TypeDecorator):
    """pgvector on Postgres; plain JSON elsewhere (SQLite in unit tests)."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(EMBEDDING_DIM))
        return dialect.type_descriptor(JSON())


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class User(Base):
    """One master record per person: verified identity, customer, and lead owner."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email_index", name="uq_users_tenant_email"),
        Index("ix_users_phone_index", "phone_index"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    role: Mapped[str] = mapped_column(String(20), default="verified")  # verified | staff
    name_enc: Mapped[str] = mapped_column(Text)
    email_enc: Mapped[str] = mapped_column(Text)
    email_index: Mapped[str] = mapped_column(String(64))
    phone_enc: Mapped[str] = mapped_column(Text)
    phone_index: Mapped[str] = mapped_column(String(64))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    marketing_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    memory_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (Index("ix_sessions_user", "user_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    thread_id: Mapped[str] = mapped_column(String(32), unique=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    turns: Mapped[list["Turn"]] = relationship(back_populates="session")


class Turn(Base):
    """One user message and the assistant reply. Content is stored pseudonymized."""

    __tablename__ = "turns"
    __table_args__ = (Index("ix_turns_session_created", "session_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    user_text: Mapped[str] = mapped_column(Text)
    reply_text: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    agent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    eval_verdict: Mapped[str | None] = mapped_column(String(12), nullable=True)
    eval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    session: Mapped[Session] = relationship(back_populates="turns")


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    turn_id: Mapped[str | None] = mapped_column(ForeignKey("turns.id"), nullable=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    tool: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(12))
    input_redacted: Mapped[dict] = mapped_column(JSON, default=dict)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    stage: Mapped[str] = mapped_column(String(20), default="new")
    need_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget_range: Mapped[str | None] = mapped_column(String(60), nullable=True)
    timeline: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class FunnelEvent(Base):
    __tablename__ = "funnel_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"))
    from_stage: Mapped[str] = mapped_column(String(20))
    to_stage: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Quote(Base):
    """Prices come only from the Quoting service; the hash lets payment verify nothing changed."""

    __tablename__ = "quotes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    lead_id: Mapped[str] = mapped_column(ForeignKey("leads.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    line_items: Mapped[list] = mapped_column(JSON, default=list)
    total_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="CAD")
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | needs_approval | approved | accepted | expired
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Escalation(Base):
    __tablename__ = "escalations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    reference: Mapped[str] = mapped_column(String(16), unique=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    reason: Mapped[str] = mapped_column(String(60))
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DocumentChunk(Base):
    """Company knowledge, chunked and embedded. Vector search is pgvector (HNSW); keyword search is BM25 in the app."""

    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("tenant_id", "source", "chunk_index", name="uq_chunks_source_index"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    source: Mapped[str] = mapped_column(String(300))
    doc_hash: Mapped[str] = mapped_column(String(64))
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(EmbeddingType())
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # set when the text came from OCR
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class OAuthToken(Base):
    """Per-user provider grant. The refresh token is encrypted; access tokens are cached briefly in the key-value store."""

    __tablename__ = "oauth_tokens"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_oauth_user_provider"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    refresh_enc: Mapped[str] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MemoryRow(Base):
    """Long-term memory item. Text is validated to contain no contact details or privacy tokens."""

    __tablename__ = "memories"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    slot: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    superseded_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
