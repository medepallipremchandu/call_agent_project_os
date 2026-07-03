from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    credentials: Mapped[list["ProviderCredential"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["ApiKey"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class ProviderCredential(Base):
    """One row per (organization, credential_type). credential_type is either
    'telephony' or 'ai'. `provider` names which adapter to use (twilio /
    azure_openai / openai). `encrypted_payload` is a Fernet-encrypted JSON blob
    of provider-specific fields — see app/core/crypto.py.
    """

    __tablename__ = "provider_credentials"
    __table_args__ = (UniqueConstraint("organization_id", "credential_type", name="uq_org_credential_type"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    credential_type: Mapped[str] = mapped_column(String(16), nullable=False)  # telephony | ai
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # twilio | azure_openai | openai
    encrypted_payload: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="credentials")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="api_keys")


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("organization_id", "key", name="uq_org_idempotency_key"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    to_number: Mapped[str] = mapped_column(String(32), nullable=False)
    from_number: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    max_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    call_script: Mapped[dict] = mapped_column(JSONB, nullable=False)
    webhook_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    provider_call_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extracted_fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    consent_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # granted | denied | unclear
    warned_2min: Mapped[bool] = mapped_column(default=False)
    warned_1min: Mapped[bool] = mapped_column(default=False)
    end_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list["CallEvent"]] = relationship(back_populates="call", cascade="all, delete-orphan")
    turns: Mapped[list["ConversationTurn"]] = relationship(back_populates="call", cascade="all, delete-orphan")
    summary: Mapped["CallSummary | None"] = relationship(back_populates="call", cascade="all, delete-orphan")


class CallEvent(Base):
    __tablename__ = "call_events"
    __table_args__ = (Index("ix_call_events_call_id_created_at", "call_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    call: Mapped["Call"] = relationship(back_populates="events")


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    # Unique, not just indexed: a duplicate Twilio webhook delivery for the
    # same turn must fail loudly (IntegrityError) rather than silently insert
    # a second row for that turn — see _append_turn() in routers/webhooks.py.
    __table_args__ = (UniqueConstraint("call_id", "turn_index", name="uq_conversation_turn_call_id_turn_index"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(String(16), nullable=False)  # ai | callee
    text: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    call: Mapped["Call"] = relationship(back_populates="turns")


class CallSummary(Base):
    __tablename__ = "call_summaries"

    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id"), primary_key=True)
    summary_text: Mapped[str] = mapped_column(String, nullable=False)
    extracted_fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    call: Mapped["Call"] = relationship(back_populates="summary")
