"""Schemas for conversation APIs."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MessageRole = Literal["user", "agent"]
ToolCallStatus = Literal["pending", "running", "completed", "failed"]


class ConversationCreate(BaseModel):
    """Request body for creating a conversation."""

    user_id: str = Field(..., min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=200)


class ConversationUpdate(BaseModel):
    """Request body for updating a conversation."""

    title: str | None = Field(default=None, max_length=200)


class ConversationResponse(BaseModel):
    """Conversation response body."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


class ToolCallCreate(BaseModel):
    """Request body for a tool call attached to a message."""

    tool_call_id: str | None = Field(default=None, max_length=200)
    name: str = Field(..., min_length=1, max_length=200)
    arguments: dict[str, Any] | None = None
    result: dict[str, Any] | str | None = None
    status: ToolCallStatus = "completed"
    sequence: int = 0


class ToolCallUpdate(BaseModel):
    """Request body for updating a tool call."""

    tool_call_id: str | None = Field(default=None, max_length=200)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    arguments: dict[str, Any] | None = None
    result: dict[str, Any] | str | None = None
    status: ToolCallStatus | None = None
    sequence: int | None = None


class ToolCallResponse(BaseModel):
    """Tool call response body."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    message_id: str
    tool_call_id: str | None
    name: str
    arguments: dict[str, Any] | None
    result: dict[str, Any] | str | None
    status: ToolCallStatus
    sequence: int
    created_at: datetime
    updated_at: datetime


class ReasoningCreate(BaseModel):
    """Request body for a reasoning entry attached to a message."""

    content: str = Field(..., min_length=1)
    summary: str | None = None
    metadata: dict[str, Any] | None = None
    sequence: int = 0


class ReasoningUpdate(BaseModel):
    """Request body for updating a reasoning entry."""

    content: str | None = Field(default=None, min_length=1)
    summary: str | None = None
    metadata: dict[str, Any] | None = None
    sequence: int | None = None


class ReasoningResponse(BaseModel):
    """Reasoning entry response body."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    message_id: str
    content: str
    summary: str | None
    metadata: dict[str, Any] | None = Field(
        validation_alias="reasoning_metadata",
        serialization_alias="metadata",
    )
    sequence: int
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    """Request body for creating a conversation message."""

    role: MessageRole
    text: str | None = None
    tool_calls: list[ToolCallCreate] = Field(default_factory=list)
    reasoning_entries: list[ReasoningCreate] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_content(self) -> "MessageCreate":
        """Validate that the message has at least one useful content item."""
        if not has_message_content(
            text=self.text,
            tool_calls=self.tool_calls,
            reasoning_entries=self.reasoning_entries,
        ):
            raise ValueError("message requires text, tool_calls, or reasoning_entries")
        return self


class MessageUpdate(BaseModel):
    """Request body for updating a conversation message."""

    role: MessageRole | None = None
    text: str | None = None
    metadata: dict[str, Any] | None = None


class MessageResponse(BaseModel):
    """Conversation message response body."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: MessageRole
    text: str | None
    tool_calls: list[ToolCallResponse] = Field(default_factory=list)
    reasoning_entries: list[ReasoningResponse] = Field(default_factory=list)
    metadata: dict[str, Any] | None = Field(
        validation_alias="message_metadata",
        serialization_alias="metadata",
    )
    created_at: datetime
    updated_at: datetime


class ConversationWithMessagesResponse(ConversationResponse):
    """Conversation response body with nested messages."""

    messages: list[MessageResponse]


def has_message_content(
    *,
    text: str | None,
    tool_calls: list[ToolCallCreate],
    reasoning_entries: list[ReasoningCreate],
) -> bool:
    """Return whether a message has at least one content item."""
    return bool((text and text.strip()) or tool_calls or reasoning_entries)
