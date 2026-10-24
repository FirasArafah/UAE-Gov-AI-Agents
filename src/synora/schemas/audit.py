from uuid import UUID
from datetime import datetime
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
    created_at: datetime

class PolicyGapRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    gap_type: GapType
    description: str
    global_best_practice: str | None
    severity: str