import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _default_dict() -> dict:
    return {}


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, server_default='{}')
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )

    def __init__(self, **kwargs: Any) -> None:
        # SQLAlchemy column defaults only fire at INSERT time; populate here
        # so model instances have correct values when constructed without a session.
        if "id" not in kwargs:
            kwargs["id"] = uuid.uuid4()
        if "status" not in kwargs:
            kwargs["status"] = 1
        if "metadata_" not in kwargs:
            kwargs["metadata_"] = {}
        if "created_at" not in kwargs:
            kwargs["created_at"] = _utcnow()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = _utcnow()
        super().__init__(**kwargs)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # 'user' | 'assistant'
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), server_default="completed")  # streaming | completed | failed
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")
    tool_calls: Mapped[list["ToolCall"]] = relationship(
        "ToolCall", back_populates="message", cascade="all, delete-orphan"
    )

    def __init__(self, **kwargs: Any) -> None:
        # SQLAlchemy column defaults only fire at INSERT time; populate here
        # so model instances have correct values when constructed without a session.
        if "id" not in kwargs:
            kwargs["id"] = uuid.uuid4()
        if "status" not in kwargs:
            kwargs["status"] = "completed"
        if "created_at" not in kwargs:
            kwargs["created_at"] = _utcnow()
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = _utcnow()
        super().__init__(**kwargs)


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    tool_call_id: Mapped[str] = mapped_column(String, nullable=False)
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    tool_input: Mapped[dict] = mapped_column(JSONB, server_default='{}')
    tool_output: Mapped[dict] = mapped_column(JSONB, server_default='{}')
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    message: Mapped["Message"] = relationship("Message", back_populates="tool_calls")

    def __init__(self, **kwargs: Any) -> None:
        # SQLAlchemy column defaults only fire at INSERT time; populate here
        # so model instances have correct values when constructed without a session.
        if "id" not in kwargs:
            kwargs["id"] = uuid.uuid4()
        if "tool_input" not in kwargs:
            kwargs["tool_input"] = {}
        if "tool_output" not in kwargs:
            kwargs["tool_output"] = {}
        if "created_at" not in kwargs:
            kwargs["created_at"] = _utcnow()
        super().__init__(**kwargs)
