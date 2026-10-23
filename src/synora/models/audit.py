from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from synora.db.base import Base
from synora.models.enums import AuditAction, DocumentDomain, GapType


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("simulation_sessions.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), index=True
    )
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    action: Mapped[AuditAction] = mapped_column(String(30), index=True)
    reasoning: Mapped[str | None] = mapped_column(Text)
    policy_references: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    source_attributions: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    confidence: Mapped[float | None] = mapped_column(Float)
    audit_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class PolicyGap(Base):
    __tablename__ = "policy_gaps"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("simulation_sessions.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL")
    )
    gap_type: Mapped[GapType] = mapped_column(String(30), index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    affected_domain: Mapped[DocumentDomain] = mapped_column(String(50))
    global_best_practice: Mapped[str | None] = mapped_column(Text)
    global_references: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(30), default="identified")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )