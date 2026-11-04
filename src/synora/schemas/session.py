from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from synora.models.enums import SimulationStatus


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scenario_id: UUID
    status: SimulationStatus
    current_sequence: int
    human_in_loop: bool
    created_at: datetime


class SessionSummary(SessionRead):
    scenario_slug: str
    scenario_title: str
    message_count: int


class ChatSummary(BaseModel):
    id: UUID
    title: str
    created_at: datetime


class SessionCreateRequest(BaseModel):
    scenario_id: UUID | None = None
