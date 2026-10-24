from pydantic import BaseModel, Field


class StreamMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message")
    agents: list[str] = Field(
        default_factory=lambda: ["coordinator"],
        description="Ordered list of agent slugs to invoke",
    )
