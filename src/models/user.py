"""User database models."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.common import json_type, utc_now


class User(Base):
    """A Clerk-backed user profile keyed by the Clerk user id."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    username: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(400), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)

    work_function: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    job_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    team_size: Mapped[str | None] = mapped_column(String(30), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    locale: Mapped[str | None] = mapped_column(String(20), nullable=True)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    preferences: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict)

    public_metadata: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict)
    private_metadata: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict)
    unsafe_metadata: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict)

    password_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    banned: Mapped[bool] = mapped_column(Boolean, default=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)

    last_sign_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    clerk_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    clerk_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
