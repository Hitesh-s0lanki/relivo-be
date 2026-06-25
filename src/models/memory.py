"""Long-term user memory database models."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.common import json_type, utc_now, uuid_str


class Memory(Base):
    """A concise, reusable memory attached to one user."""

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(String(200), index=True)
    type: Mapped[str] = mapped_column(String(30), index=True)
    summary: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(json_type, default=list)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.8)
    source_message_ids: Mapped[list[str]] = mapped_column(json_type, default=list)
    memory_metadata: Mapped[dict[str, Any] | None] = mapped_column(json_type, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
