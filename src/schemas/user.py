"""Schemas for the Clerk-backed user profile API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Suggested, not enforced: the column is free text so new functions do not need a
# migration. The frontend offers these as options.
SUGGESTED_WORK_FUNCTIONS = (
    "engineering",
    "product",
    "design",
    "data",
    "marketing",
    "sales",
    "finance",
    "operations",
    "hr",
    "legal",
    "founder",
    "student",
    "other",
)

MAX_LIST_LIMIT = 200
DEFAULT_LIST_LIMIT = 50


class UserWritableFields(BaseModel):
    """
    Fields a client may write.

    Every field is optional so `PATCH` can send one and `PUT` can send only what
    the caller actually knows. Lengths mirror the column widths, turning what
    would be a database truncation error into a 422.
    """

    model_config = ConfigDict(extra="forbid")

    # Clerk-owned: refreshed from Clerk on every sync.
    external_id: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    email_verified: bool | None = None
    phone_number: str | None = Field(default=None, max_length=30)
    username: str | None = Field(default=None, max_length=200)
    first_name: str | None = Field(default=None, max_length=200)
    last_name: str | None = Field(default=None, max_length=200)
    full_name: str | None = Field(default=None, max_length=400)
    image_url: str | None = Field(default=None, max_length=1024)
    has_image: bool | None = None
    public_metadata: dict[str, Any] | None = None
    private_metadata: dict[str, Any] | None = None
    unsafe_metadata: dict[str, Any] | None = None
    password_enabled: bool | None = None
    two_factor_enabled: bool | None = None
    banned: bool | None = None
    locked: bool | None = None
    last_sign_in_at: datetime | None = None
    last_active_at: datetime | None = None
    clerk_created_at: datetime | None = None
    clerk_updated_at: datetime | None = None

    # App-owned: only changed when explicitly supplied, so a re-sync preserves them.
    work_function: str | None = Field(default=None, max_length=100)
    job_title: str | None = Field(default=None, max_length=200)
    company_name: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=100)
    team_size: str | None = Field(default=None, max_length=30)
    timezone: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, max_length=20)
    onboarding_completed: bool | None = None
    preferences: dict[str, Any] | None = None


class UserCreate(UserWritableFields):
    """Body for `POST /users`. The id must be the Clerk user id."""

    id: str = Field(..., min_length=1, max_length=200)


class UserUpsert(UserWritableFields):
    """Body for `PUT /users/{user_id}`. The id comes from the path."""


class UserUpdate(UserWritableFields):
    """Body for `PATCH /users/{user_id}`. Omitted fields are untouched."""


class UserResponse(BaseModel):
    """A full user record. `private_metadata` is deliberately absent."""

    id: str
    external_id: str | None
    email: str | None
    email_verified: bool
    phone_number: str | None
    username: str | None
    first_name: str | None
    last_name: str | None
    full_name: str | None
    image_url: str | None
    has_image: bool
    work_function: str | None
    job_title: str | None
    company_name: str | None
    industry: str | None
    team_size: str | None
    timezone: str | None
    locale: str | None
    onboarding_completed: bool
    preferences: dict[str, Any]
    public_metadata: dict[str, Any]
    unsafe_metadata: dict[str, Any]
    password_enabled: bool
    two_factor_enabled: bool
    banned: bool
    locked: bool
    last_sign_in_at: datetime | None
    last_active_at: datetime | None
    clerk_created_at: datetime | None
    clerk_updated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserSummaryResponse(BaseModel):
    """A user as returned by `GET /users`."""

    id: str
    email: str | None
    full_name: str | None
    work_function: str | None
    job_title: str | None
    onboarding_completed: bool
    created_at: datetime
    updated_at: datetime


class ClerkWebhookResponse(BaseModel):
    """Acknowledgement for `POST /users/clerk/webhook`."""

    received: bool
    event: str
    user_id: str | None
