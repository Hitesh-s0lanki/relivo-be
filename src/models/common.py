"""Common model helpers."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def uuid_str() -> str:
    """Return a new UUID string."""
    return str(uuid.uuid4())


json_type = JSON().with_variant(JSONB, "postgresql")
