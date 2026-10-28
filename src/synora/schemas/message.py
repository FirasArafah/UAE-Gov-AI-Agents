from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from synora.models.enums import MessageRole


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    agent_id: UUID | None
    role: MessageRole
    content: str
    thinking_trace: str | None
    sequence: int
    created_at: datetime
