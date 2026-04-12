import uuid
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(..., description="ID of the user making the request")
    conversation_id: uuid.UUID | None = Field(
        None,
        description="Existing conversation ID. If omitted, a new conversation is created.",
    )
    message: str = Field(..., min_length=1, description="The user's message text")
