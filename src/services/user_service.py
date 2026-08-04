"""Service for Clerk-backed user profiles."""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.schemas.user import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    UserCreate,
    UserUpdate,
    UserUpsert,
)

logger = logging.getLogger(__name__)

# Fields Clerk owns. Everything else on the row is app-owned and only changes
# when a request explicitly supplies it.
CLERK_OWNED_FIELDS = frozenset(
    {
        "external_id",
        "email",
        "email_verified",
        "phone_number",
        "username",
        "first_name",
        "last_name",
        "full_name",
        "image_url",
        "has_image",
        "public_metadata",
        "private_metadata",
        "unsafe_metadata",
        "password_enabled",
        "two_factor_enabled",
        "banned",
        "locked",
        "last_sign_in_at",
        "last_active_at",
        "clerk_created_at",
        "clerk_updated_at",
    }
)


class UserNotFoundError(Exception):
    """Raised when no user row exists for the given Clerk id."""


class UserAlreadyExistsError(Exception):
    """Raised when creating a user whose id is already taken."""


class UserService:
    """Create, read, update, and delete Clerk-backed user profiles."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to a database session."""
        self.session = session

    async def list_users(
        self,
        *,
        work_function: str | None = None,
        onboarding_completed: bool | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> list[User]:
        """Return a page of users, newest first."""
        query = select(User).order_by(User.created_at.desc())
        if work_function is not None:
            query = query.where(User.work_function == work_function)
        if onboarding_completed is not None:
            query = query.where(User.onboarding_completed == onboarding_completed)

        query = query.limit(min(max(limit, 1), MAX_LIST_LIMIT)).offset(max(offset, 0))
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def find_user(self, user_id: str) -> User | None:
        """Return one user, or None when the row does not exist."""
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_user(self, user_id: str) -> User:
        """Return one user."""
        user = await self.find_user(user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        return user

    async def create_user(self, payload: UserCreate) -> User:
        """Create one user row. The id must be the Clerk user id."""
        if await self.find_user(payload.id) is not None:
            raise UserAlreadyExistsError(payload.id)

        values = payload.model_dump(exclude_unset=True, exclude={"id"})
        user = User(id=payload.id, **values)
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        logger.info("user created id=%s", user.id)
        return user

    async def upsert_user(self, user_id: str, payload: UserUpsert) -> User:
        """
        Create the row when missing, refresh it otherwise.

        Only the fields present in the body are written, so a sync that carries
        Clerk identity alone cannot wipe app-owned answers collected elsewhere.
        """
        values = payload.model_dump(exclude_unset=True)
        user = await self.find_user(user_id)

        if user is None:
            user = User(id=user_id, **values)
            self.session.add(user)
            logger.info("user upsert created id=%s", user_id)
        else:
            _apply(user, values)
            logger.info("user upsert updated id=%s fields=%s", user_id, sorted(values))

        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def update_user(self, user_id: str, payload: UserUpdate) -> User:
        """Apply a partial update. Explicit nulls clear nullable fields."""
        user = await self.get_user(user_id)
        values = payload.model_dump(exclude_unset=True)
        _apply(user, values)

        await self.session.commit()
        await self.session.refresh(user)
        logger.info("user updated id=%s fields=%s", user_id, sorted(values))
        return user

    async def delete_user(self, user_id: str) -> None:
        """
        Delete a user row.

        Conversations, files, and memories have no foreign key to this table and
        are deliberately left intact.
        """
        user = await self.get_user(user_id)
        await self.session.delete(user)
        await self.session.commit()
        logger.info("user deleted id=%s", user_id)

    async def get_preferences(self, user_id: str) -> dict[str, Any]:
        """Return the user's preference bag."""
        user = await self.get_user(user_id)
        return dict(user.preferences or {})

    async def merge_preferences(
        self,
        user_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Shallow-merge into the preference bag. A null value removes its key."""
        user = await self.get_user(user_id)
        merged = dict(user.preferences or {})

        for key, value in patch.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value

        return await self._store_preferences(user, merged)

    async def replace_preferences(
        self,
        user_id: str,
        preferences: dict[str, Any],
    ) -> dict[str, Any]:
        """Replace the whole preference bag."""
        user = await self.get_user(user_id)
        return await self._store_preferences(user, dict(preferences))

    async def apply_clerk_event(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> str | None:
        """Apply one Clerk webhook event to the local row."""
        user_id = data.get("id")
        if not isinstance(user_id, str) or not user_id:
            return None

        if event_type == "user.deleted":
            user = await self.find_user(user_id)
            if user is not None:
                await self.session.delete(user)
                await self.session.commit()
            logger.info("user webhook delete id=%s", user_id)
            return user_id

        values = clerk_payload_to_fields(data)
        user = await self.find_user(user_id)

        if user is None:
            user = User(id=user_id, **values)
            self.session.add(user)
        else:
            # user.updated must not disturb app-owned answers.
            _apply(user, {k: v for k, v in values.items() if k in CLERK_OWNED_FIELDS})

        await self.session.commit()
        logger.info("user webhook %s id=%s", event_type, user_id)
        return user_id

    async def _store_preferences(
        self,
        user: User,
        preferences: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Persist a new preference bag.

        A fresh dict is assigned rather than mutated in place: the JSON column is
        not wrapped in `MutableDict`, so SQLAlchemy would not notice the change.
        """
        user.preferences = preferences
        await self.session.commit()
        await self.session.refresh(user)
        return dict(user.preferences or {})


def _apply(user: User, values: dict[str, Any]) -> None:
    """Assign supplied values onto a user row."""
    for field, value in values.items():
        setattr(user, field, value)


def clerk_payload_to_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Map a Clerk webhook `data` object onto column values."""
    primary_email = _primary_of(
        data.get("email_addresses"),
        data.get("primary_email_address_id"),
    )
    primary_phone = _primary_of(
        data.get("phone_numbers"),
        data.get("primary_phone_number_id"),
    )
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    full_name = " ".join(part for part in (first_name, last_name) if part) or None

    return {
        "external_id": data.get("external_id"),
        "email": (primary_email or {}).get("email_address"),
        "email_verified": _is_verified(primary_email),
        "phone_number": (primary_phone or {}).get("phone_number"),
        "username": data.get("username"),
        "first_name": first_name,
        "last_name": last_name,
        "full_name": full_name,
        "image_url": data.get("image_url"),
        "has_image": bool(data.get("has_image", False)),
        "public_metadata": data.get("public_metadata") or {},
        "private_metadata": data.get("private_metadata") or {},
        "unsafe_metadata": data.get("unsafe_metadata") or {},
        "password_enabled": bool(data.get("password_enabled", False)),
        "two_factor_enabled": bool(data.get("two_factor_enabled", False)),
        "banned": bool(data.get("banned", False)),
        "locked": bool(data.get("locked", False)),
        "last_sign_in_at": _to_datetime(data.get("last_sign_in_at")),
        "last_active_at": _to_datetime(data.get("last_active_at")),
        "clerk_created_at": _to_datetime(data.get("created_at")),
        "clerk_updated_at": _to_datetime(data.get("updated_at")),
    }


def _primary_of(
    entries: Any,
    primary_id: Any,
) -> dict[str, Any] | None:
    """Pick the primary entry from a Clerk identifier list."""
    if not isinstance(entries, list) or not entries:
        return None

    for entry in entries:
        if isinstance(entry, dict) and entry.get("id") == primary_id:
            return entry

    first = entries[0]
    return first if isinstance(first, dict) else None


def _is_verified(entry: dict[str, Any] | None) -> bool:
    """Return whether a Clerk identifier carries a verified status."""
    if not entry:
        return False

    verification = entry.get("verification")
    return isinstance(verification, dict) and verification.get("status") == "verified"


def _to_datetime(value: Any) -> datetime | None:
    """Convert Clerk's epoch milliseconds into an aware datetime."""
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None

    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
