"""Schemas for chat API requests and responses."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.schemas.user_file import AttachmentInput


class ChatRequest(BaseModel):
    """Request body for streaming chat."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "user_message": "Help me plan my day",
                    "thread_id": "user-123",
                    "stream_mode": ["updates", "messages"],
                }
            ]
        }
    )

    user_message: str = Field(
        default="",
        max_length=8000,
        description=(
            "User message to send to the chat agent. Blank messages are allowed only when "
            "attachments are provided."
        ),
        examples=["Help me plan my day"],
    )
    thread_id: str = Field(
        default="demo",
        min_length=1,
        max_length=200,
        description="Conversation thread identifier used by the agent memory/checkpointer.",
        examples=["user-123"],
    )
    stream_mode: tuple[Literal["updates", "messages"], ...] = Field(
        default=("updates", "messages"),
        description="Agent stream event types to include in the SSE response.",
        examples=[["updates", "messages"]],
    )
    attachments: list[AttachmentInput] = Field(
        default_factory=list,
        description="Uploaded attachment references to include in the chat turn.",
    )

    @model_validator(mode="after")
    def validate_content(self) -> "ChatRequest":
        """Require text or at least one uploaded attachment."""
        if not self.user_message.strip() and not self.attachments:
            raise ValueError("user_message or attachments is required")
        return self


class ChatErrorResponse(BaseModel):
    """Error response body exposed to clients and services."""

    status: int = Field(..., description="HTTP-style status code for the error.", examples=[500])
    message: str = Field(
        ...,
        description="Human-readable error message.",
        examples=["chat stream failed"],
    )
    error_tag: str = Field(
        ...,
        description="Stable machine-readable error identifier.",
        examples=["chat_stream_failed"],
    )
