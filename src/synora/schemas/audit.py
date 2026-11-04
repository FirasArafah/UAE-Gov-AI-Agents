from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from synora.models.enums import AuditAction, GapType


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    agent_id: UUID | None
    action: AuditAction
    reasoning: str | None
    policy_references: list[dict]
    source_attributions: list[dict]
    audit_metadata: dict
    created_at: datetime


class PolicyGapRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    agent_id: UUID | None
    gap_type: GapType
    description: str
    affected_domain: str
    global_best_practice: str | None
    global_references: list[dict]
    severity: str
    status: str
    created_at: datetime


class AssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    agent_id: UUID
    event_sequence: int
    assessment: str
    confidence: float | None
    references_used: list[dict]
    created_at: datetime
