"""Schemas for conversation APIs."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from src.schemas.user_file import AttachmentInput

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
    attachments: list[AttachmentInput] = Field(default_factory=list)
    tool_calls: list[ToolCallCreate] = Field(default_factory=list)
    reasoning_entries: list[ReasoningCreate] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_content(self) -> "MessageCreate":
        """Validate that the message has at least one useful content item."""
        if not has_message_content(
            text=self.text,
            attachments=self.attachments,
            tool_calls=self.tool_calls,
            reasoning_entries=self.reasoning_entries,
            metadata=self.metadata,
        ):
            raise ValueError("message requires text, attachments, tool_calls, or reasoning_entries")
        return self

    def metadata_with_attachments(self) -> dict[str, Any] | None:
        """Return metadata with first-class attachments folded into it."""
        return metadata_with_attachments(self.metadata, self.attachments or None)


class MessageUpdate(BaseModel):
    """Request body for updating a conversation message."""

    role: MessageRole | None = None
    text: str | None = None
    attachments: list[AttachmentInput] | None = None
    metadata: dict[str, Any] | None = None

    def metadata_with_attachments(self) -> dict[str, Any] | None:
        """Return metadata with first-class attachments folded into it."""
        return metadata_with_attachments(self.metadata, self.attachments)


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

    @computed_field
    @property
    def attachments(self) -> list[AttachmentInput]:
        """Return attachments stored in message metadata."""
        return attachments_from_metadata(self.metadata)


class ConversationWithMessagesResponse(ConversationResponse):
    """Conversation response body with nested messages."""

    messages: list[MessageResponse]


def has_message_content(
    *,
    text: str | None,
    attachments: list[AttachmentInput],
    tool_calls: list[ToolCallCreate],
    reasoning_entries: list[ReasoningCreate],
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Return whether a message has at least one content item."""
    return bool(
        (text and text.strip())
        or attachments
        or attachments_from_metadata(metadata)
        or tool_calls
        or reasoning_entries
    )


def metadata_with_attachments(
    metadata: dict[str, Any] | None,
    attachments: list[AttachmentInput] | None,
) -> dict[str, Any] | None:
    """Merge first-class attachments into the JSON metadata envelope."""
    if attachments is None:
        return metadata

    next_metadata = dict(metadata or {})
    next_metadata["attachments"] = [
        attachment.model_dump(by_alias=True) for attachment in attachments
    ]
    return next_metadata


def attachments_from_metadata(metadata: dict[str, Any] | None) -> list[AttachmentInput]:
    """Parse attachment references from message metadata."""
    if not isinstance(metadata, dict):
        return []

    raw_attachments = metadata.get("attachments")
    if not isinstance(raw_attachments, list):
        return []

    attachments: list[AttachmentInput] = []
    for raw_attachment in raw_attachments:
        if not isinstance(raw_attachment, dict):
            continue
        try:
            attachments.append(AttachmentInput.model_validate(raw_attachment))
        except ValueError:
            continue
    return attachments
