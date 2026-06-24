"""Conversation message database models."""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.models.common import json_type, utc_now, uuid_str

if TYPE_CHECKING:
    from src.models.conversation import Conversation


class ConversationMessage(Base):
    """A user or agent message inside a conversation."""

    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), index=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_metadata: Mapped[dict[str, Any] | None] = mapped_column(json_type, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    tool_calls: Mapped[list["ConversationMessageToolCall"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ConversationMessageToolCall.sequence",
    )
    reasoning_entries: Mapped[list["ConversationMessageReasoning"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ConversationMessageReasoning.sequence",
    )


class ConversationMessageToolCall(Base):
    """A tool call associated with one agent message."""

    __tablename__ = "conversation_message_tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    message_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversation_messages.id", ondelete="CASCADE"),
        index=True,
    )
    tool_call_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    arguments: Mapped[dict[str, Any] | None] = mapped_column(json_type, nullable=True)
    result: Mapped[dict[str, Any] | str | None] = mapped_column(json_type, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="completed", index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    message: Mapped[ConversationMessage] = relationship(back_populates="tool_calls")


class ConversationMessageReasoning(Base):
    """A reasoning record associated with one agent message."""

    __tablename__ = "conversation_message_reasoning_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    message_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversation_messages.id", ondelete="CASCADE"),
        index=True,
    )
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning_metadata: Mapped[dict[str, Any] | None] = mapped_column(json_type, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    message: Mapped[ConversationMessage] = relationship(back_populates="reasoning_entries")
