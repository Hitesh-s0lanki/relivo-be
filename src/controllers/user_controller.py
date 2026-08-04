"""User profile HTTP controller."""

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db_session
from src.models.user import User
from src.schemas.user import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    ClerkWebhookResponse,
    UserCreate,
    UserResponse,
    UserSummaryResponse,
    UserUpdate,
    UserUpsert,
)
from src.services.user_service import (
    UserAlreadyExistsError,
    UserNotFoundError,
    UserService,
)
from src.utils.clerk_webhook import (
    ClerkWebhookSecretMissingError,
    ClerkWebhookSignatureError,
    verify_clerk_webhook,
)
from src.utils.error_response import build_error_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["Users"])

UserIdPath = Annotated[str, Path(min_length=1, max_length=200)]

SUPPORTED_WEBHOOK_EVENTS = frozenset({"user.created", "user.updated", "user.deleted"})


def get_user_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserService:
    """Resolve the user service dependency."""
    return UserService(session)


UserServiceDependency = Annotated[UserService, Depends(get_user_service)]


@router.get("", response_model=list[UserSummaryResponse])
async def list_users(
    service: UserServiceDependency,
    work_function: Annotated[str | None, Query(max_length=100)] = None,
    onboarding_completed: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = DEFAULT_LIST_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserSummaryResponse]:
    """List users, newest first."""
    users = await service.list_users(
        work_function=work_function,
        onboarding_completed=onboarding_completed,
        limit=limit,
        offset=offset,
    )
    return [_to_summary(user) for user in users]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    service: UserServiceDependency,
) -> UserResponse:
    """Create one user row keyed by the Clerk user id."""
    with _translated_errors():
        user = await service.create_user(payload)
    return _to_response(user)


# Registered before `/{user_id}` so the literal path is never captured as an id.
@router.post("/clerk/webhook", response_model=ClerkWebhookResponse)
async def clerk_webhook(
    request: Request,
    service: UserServiceDependency,
    svix_id: Annotated[str | None, Header(alias="svix-id")] = None,
    svix_timestamp: Annotated[str | None, Header(alias="svix-timestamp")] = None,
    svix_signature: Annotated[str | None, Header(alias="svix-signature")] = None,
) -> ClerkWebhookResponse:
    """Apply a Clerk `user.*` event after verifying its Svix signature."""
    body = await request.body()

    try:
        verify_clerk_webhook(
            body=body,
            svix_id=svix_id,
            svix_timestamp=svix_timestamp,
            svix_signature=svix_signature,
        )
    except ClerkWebhookSecretMissingError as exc:
        raise _http_error(
            503,
            "clerk webhook secret is not configured on this server",
            "clerk_webhook_secret_missing",
        ) from exc
    except ClerkWebhookSignatureError as exc:
        raise _http_error(
            400,
            "invalid clerk webhook signature",
            "clerk_webhook_invalid_signature",
        ) from exc

    try:
        event = json.loads(body)
    except ValueError as exc:
        raise _http_error(400, "invalid clerk webhook payload", "clerk_webhook_invalid") from exc

    event_type = event.get("type") if isinstance(event, dict) else None
    data = event.get("data") if isinstance(event, dict) else None

    if not isinstance(event_type, str) or not isinstance(data, dict):
        raise _http_error(400, "invalid clerk webhook payload", "clerk_webhook_invalid")

    if event_type not in SUPPORTED_WEBHOOK_EVENTS:
        # Acknowledge so Clerk stops retrying an event we intentionally ignore.
        logger.info("clerk webhook ignored event=%s", event_type)
        return ClerkWebhookResponse(received=True, event=event_type, user_id=None)

    user_id = await service.apply_clerk_event(event_type, data)
    return ClerkWebhookResponse(received=True, event=event_type, user_id=user_id)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UserIdPath,
    service: UserServiceDependency,
) -> UserResponse:
    """Read one user."""
    with _translated_errors():
        user = await service.get_user(user_id)
    return _to_response(user)


@router.put("/{user_id}", response_model=UserResponse)
async def upsert_user(
    user_id: UserIdPath,
    payload: UserUpsert,
    service: UserServiceDependency,
) -> UserResponse:
    """Create the user when missing, refresh them otherwise."""
    with _translated_errors():
        user = await service.upsert_user(user_id, payload)
    return _to_response(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UserIdPath,
    payload: UserUpdate,
    service: UserServiceDependency,
) -> UserResponse:
    """Apply a partial update to one user."""
    with _translated_errors():
        user = await service.update_user(user_id, payload)
    return _to_response(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UserIdPath,
    service: UserServiceDependency,
) -> None:
    """Delete one user row, leaving their conversations and files intact."""
    with _translated_errors():
        await service.delete_user(user_id)


@router.get("/{user_id}/preferences", response_model=dict[str, Any])
async def get_preferences(
    user_id: UserIdPath,
    service: UserServiceDependency,
) -> dict[str, Any]:
    """Read the user's preference bag."""
    with _translated_errors():
        return await service.get_preferences(user_id)


@router.patch("/{user_id}/preferences", response_model=dict[str, Any])
async def merge_preferences(
    user_id: UserIdPath,
    service: UserServiceDependency,
    payload: Annotated[dict[str, Any], Body(...)],
) -> dict[str, Any]:
    """Shallow-merge into the preference bag. A null value removes its key."""
    with _translated_errors():
        return await service.merge_preferences(user_id, payload)


@router.put("/{user_id}/preferences", response_model=dict[str, Any])
async def replace_preferences(
    user_id: UserIdPath,
    service: UserServiceDependency,
    payload: Annotated[dict[str, Any], Body(...)],
) -> dict[str, Any]:
    """Replace the whole preference bag. Send `{}` to clear it."""
    with _translated_errors():
        return await service.replace_preferences(user_id, payload)


def _to_response(user: User) -> UserResponse:
    """Build the full API response for a user row."""
    return UserResponse(
        id=user.id,
        external_id=user.external_id,
        email=user.email,
        email_verified=user.email_verified,
        phone_number=user.phone_number,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=user.full_name,
        image_url=user.image_url,
        has_image=user.has_image,
        work_function=user.work_function,
        job_title=user.job_title,
        company_name=user.company_name,
        industry=user.industry,
        team_size=user.team_size,
        timezone=user.timezone,
        locale=user.locale,
        onboarding_completed=user.onboarding_completed,
        preferences=user.preferences or {},
        public_metadata=user.public_metadata or {},
        unsafe_metadata=user.unsafe_metadata or {},
        password_enabled=user.password_enabled,
        two_factor_enabled=user.two_factor_enabled,
        banned=user.banned,
        locked=user.locked,
        last_sign_in_at=user.last_sign_in_at,
        last_active_at=user.last_active_at,
        clerk_created_at=user.clerk_created_at,
        clerk_updated_at=user.clerk_updated_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _to_summary(user: User) -> UserSummaryResponse:
    """Build the list API response for a user row."""
    return UserSummaryResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        work_function=user.work_function,
        job_title=user.job_title,
        onboarding_completed=user.onboarding_completed,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


class _translated_errors:  # noqa: N801 - context manager used like a decorator
    """Translate service errors into the standard API error shape."""

    def __enter__(self) -> "_translated_errors":
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        if exc is None:
            return False
        if isinstance(exc, UserNotFoundError):
            raise _http_error(404, "user not found", "user_not_found") from exc
        if isinstance(exc, UserAlreadyExistsError):
            raise _http_error(409, "user already exists", "user_already_exists") from exc
        return False


def _http_error(status_code: int, message: str, error_tag: str) -> HTTPException:
    """Build an HTTPException carrying the standard error body."""
    error = build_error_response(status=status_code, message=message, error_tag=error_tag)
    return HTTPException(status_code=status_code, detail=error.model_dump())
