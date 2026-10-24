from uuid import UUID
from pydantic import BaseModel, ConfigDict
from synora.models.enums import AgentRole

class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    slug: str
    name: str
    role: AgentRole
    mandate: str
    is_active: bool