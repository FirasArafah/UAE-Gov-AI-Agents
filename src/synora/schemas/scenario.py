from uuid import UUID
from pydantic import BaseModel, ConfigDict
from synora.models.enums import DocumentDomain

class ScenarioEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    sequence: int
    release_after_seconds: int
    title: str
    content: str
    target_agent_roles: list[str]

class ScenarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    slug: str
    title: str
    description: str
    domain: DocumentDomain
    events: list[ScenarioEventRead] = []