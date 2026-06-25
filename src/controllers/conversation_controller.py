"""Conversation HTTP controller."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db_session
from src.schemas.conversation import (
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
    ConversationWithMessagesResponse,
    MessageCreate,
    MessageResponse,
    MessageUpdate,
    ReasoningCreate,
    ReasoningResponse,
    ReasoningUpdate,
    ToolCallCreate,
    ToolCallResponse,
    ToolCallUpdate,
)
from src.services.conversation_service import (
    ConversationNotFoundError,
    ConversationService,
    MessageNotFoundError,
    ReasoningNotFoundError,
    ToolCallNotFoundError,
)
from src.services.user_file_service import (
    S3ConfigurationError,
    S3StorageError,
    UserFileNotFoundError,
    UserFileObjectNotFoundError,
    UserFileService,
)
from src.utils.error_response import build_error_response

router = APIRouter(prefix="/conversations", tags=["Conversations"])


def get_conversation_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationService:
    """Resolve the conversation service dependency."""
    return ConversationService(session)


ConversationServiceDependency = Annotated[
    ConversationService,
    Depends(get_conversation_service),
]


def get_conversation_user_file_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserFileService:
    """Resolve user file service for attachment URL hydration."""
    return UserFileService(session)


ConversationUserFileServiceDependency = Annotated[
    UserFileService,
    Depends(get_conversation_user_file_service),
]


def not_found(status_code: int, message: str, error_tag: str) -> HTTPException:
    """Build a standard not-found HTTP exception."""
    return HTTPException(
        status_code=status_code,
        detail=build_error_response(
            status=status_code,
            message=message,
            error_tag=error_tag,
        ).model_dump(),
    )


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    service: ConversationServiceDependency,
    user_id: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> list[ConversationResponse]:
    """List conversations."""
    return await service.list_conversations(user_id=user_id)


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: ConversationCreate,
    service: ConversationServiceDependency,
) -> ConversationResponse:
    """Create a conversation."""
    return await service.create_conversation(payload)


@router.get("/{conversation_id}", response_model=ConversationWithMessagesResponse)
async def get_conversation(
    conversation_id: str,
    service: ConversationServiceDependency,
    file_service: ConversationUserFileServiceDependency,
) -> ConversationWithMessagesResponse:
    """Get a conversation with messages."""
    try:
        conversation = await service.get_conversation_with_messages(conversation_id)
        await _hydrate_message_attachment_urls(conversation.messages, file_service)
        return conversation
    except ConversationNotFoundError as exc:
        raise not_found(404, "conversation not found", "conversation_not_found") from exc


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    service: ConversationServiceDependency,
) -> ConversationResponse:
    """Update a conversation."""
    try:
        return await service.update_conversation(conversation_id, payload)
    except ConversationNotFoundError as exc:
        raise not_found(404, "conversation not found", "conversation_not_found") from exc


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    service: ConversationServiceDependency,
) -> None:
    """Delete a conversation."""
    try:
        await service.delete_conversation(conversation_id)
    except ConversationNotFoundError as exc:
        raise not_found(404, "conversation not found", "conversation_not_found") from exc


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_conversation_messages(
    conversation_id: str,
    service: ConversationServiceDependency,
    file_service: ConversationUserFileServiceDependency,
) -> list[MessageResponse]:
    """List messages in a conversation."""
    try:
        messages = await service.list_messages(conversation_id)
        await _hydrate_message_attachment_urls(messages, file_service)
        return messages
    except ConversationNotFoundError as exc:
        raise not_found(404, "conversation not found", "conversation_not_found") from exc


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation_message(
    conversation_id: str,
    payload: MessageCreate,
    service: ConversationServiceDependency,
    file_service: ConversationUserFileServiceDependency,
) -> MessageResponse:
    """Create a message in a conversation."""
    try:
        message = await service.create_message(conversation_id, payload)
        await _hydrate_message_attachment_urls([message], file_service)
        return message
    except ConversationNotFoundError as exc:
        raise not_found(404, "conversation not found", "conversation_not_found") from exc


@router.get("/{conversation_id}/messages/{message_id}", response_model=MessageResponse)
async def get_conversation_message(
    conversation_id: str,
    message_id: str,
    service: ConversationServiceDependency,
    file_service: ConversationUserFileServiceDependency,
) -> MessageResponse:
    """Get a message in a conversation."""
    try:
        message = await service.get_message(conversation_id, message_id)
        await _hydrate_message_attachment_urls([message], file_service)
        return message
    except MessageNotFoundError as exc:
        raise not_found(404, "message not found", "message_not_found") from exc


@router.patch("/{conversation_id}/messages/{message_id}", response_model=MessageResponse)
async def update_conversation_message(
    conversation_id: str,
    message_id: str,
    payload: MessageUpdate,
    service: ConversationServiceDependency,
    file_service: ConversationUserFileServiceDependency,
) -> MessageResponse:
    """Update a message in a conversation."""
    try:
        message = await service.update_message(conversation_id, message_id, payload)
        await _hydrate_message_attachment_urls([message], file_service)
        return message
    except MessageNotFoundError as exc:
        raise not_found(404, "message not found", "message_not_found") from exc


@router.delete(
    "/{conversation_id}/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation_message(
    conversation_id: str,
    message_id: str,
    service: ConversationServiceDependency,
) -> None:
    """Delete a message in a conversation."""
    try:
        await service.delete_message(conversation_id, message_id)
    except MessageNotFoundError as exc:
        raise not_found(404, "message not found", "message_not_found") from exc


@router.get(
    "/{conversation_id}/messages/{message_id}/tool-calls",
    response_model=list[ToolCallResponse],
)
async def list_message_tool_calls(
    conversation_id: str,
    message_id: str,
    service: ConversationServiceDependency,
) -> list[ToolCallResponse]:
    """List tool calls in a message."""
    try:
        return await service.list_tool_calls(conversation_id, message_id)
    except MessageNotFoundError as exc:
        raise not_found(404, "message not found", "message_not_found") from exc


@router.post(
    "/{conversation_id}/messages/{message_id}/tool-calls",
    response_model=ToolCallResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_message_tool_call(
    conversation_id: str,
    message_id: str,
    payload: ToolCallCreate,
    service: ConversationServiceDependency,
) -> ToolCallResponse:
    """Create a tool call in a message."""
    try:
        return await service.create_tool_call(conversation_id, message_id, payload)
    except MessageNotFoundError as exc:
        raise not_found(404, "message not found", "message_not_found") from exc


@router.get(
    "/{conversation_id}/messages/{message_id}/tool-calls/{tool_call_id}",
    response_model=ToolCallResponse,
)
async def get_message_tool_call(
    conversation_id: str,
    message_id: str,
    tool_call_id: str,
    service: ConversationServiceDependency,
) -> ToolCallResponse:
    """Get a tool call in a message."""
    try:
        return await service.get_tool_call(conversation_id, message_id, tool_call_id)
    except ToolCallNotFoundError as exc:
        raise not_found(404, "tool call not found", "tool_call_not_found") from exc


@router.patch(
    "/{conversation_id}/messages/{message_id}/tool-calls/{tool_call_id}",
    response_model=ToolCallResponse,
)
async def update_message_tool_call(
    conversation_id: str,
    message_id: str,
    tool_call_id: str,
    payload: ToolCallUpdate,
    service: ConversationServiceDependency,
) -> ToolCallResponse:
    """Update a tool call in a message."""
    try:
        return await service.update_tool_call(conversation_id, message_id, tool_call_id, payload)
    except ToolCallNotFoundError as exc:
        raise not_found(404, "tool call not found", "tool_call_not_found") from exc


@router.delete(
    "/{conversation_id}/messages/{message_id}/tool-calls/{tool_call_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_message_tool_call(
    conversation_id: str,
    message_id: str,
    tool_call_id: str,
    service: ConversationServiceDependency,
) -> None:
    """Delete a tool call in a message."""
    try:
        await service.delete_tool_call(conversation_id, message_id, tool_call_id)
    except ToolCallNotFoundError as exc:
        raise not_found(404, "tool call not found", "tool_call_not_found") from exc


@router.get(
    "/{conversation_id}/messages/{message_id}/reasoning",
    response_model=list[ReasoningResponse],
)
async def list_message_reasoning_entries(
    conversation_id: str,
    message_id: str,
    service: ConversationServiceDependency,
) -> list[ReasoningResponse]:
    """List reasoning entries in a message."""
    try:
        return await service.list_reasoning_entries(conversation_id, message_id)
    except MessageNotFoundError as exc:
        raise not_found(404, "message not found", "message_not_found") from exc


@router.post(
    "/{conversation_id}/messages/{message_id}/reasoning",
    response_model=ReasoningResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_message_reasoning_entry(
    conversation_id: str,
    message_id: str,
    payload: ReasoningCreate,
    service: ConversationServiceDependency,
) -> ReasoningResponse:
    """Create a reasoning entry in a message."""
    try:
        return await service.create_reasoning_entry(conversation_id, message_id, payload)
    except MessageNotFoundError as exc:
        raise not_found(404, "message not found", "message_not_found") from exc


@router.get(
    "/{conversation_id}/messages/{message_id}/reasoning/{reasoning_id}",
    response_model=ReasoningResponse,
)
async def get_message_reasoning_entry(
    conversation_id: str,
    message_id: str,
    reasoning_id: str,
    service: ConversationServiceDependency,
) -> ReasoningResponse:
    """Get a reasoning entry in a message."""
    try:
        return await service.get_reasoning_entry(conversation_id, message_id, reasoning_id)
    except ReasoningNotFoundError as exc:
        raise not_found(404, "reasoning not found", "reasoning_not_found") from exc


@router.patch(
    "/{conversation_id}/messages/{message_id}/reasoning/{reasoning_id}",
    response_model=ReasoningResponse,
)
async def update_message_reasoning_entry(
    conversation_id: str,
    message_id: str,
    reasoning_id: str,
    payload: ReasoningUpdate,
    service: ConversationServiceDependency,
) -> ReasoningResponse:
    """Update a reasoning entry in a message."""
    try:
        return await service.update_reasoning_entry(
            conversation_id,
            message_id,
            reasoning_id,
            payload,
        )
    except ReasoningNotFoundError as exc:
        raise not_found(404, "reasoning not found", "reasoning_not_found") from exc


@router.delete(
    "/{conversation_id}/messages/{message_id}/reasoning/{reasoning_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_message_reasoning_entry(
    conversation_id: str,
    message_id: str,
    reasoning_id: str,
    service: ConversationServiceDependency,
) -> None:
    """Delete a reasoning entry in a message."""
    try:
        await service.delete_reasoning_entry(conversation_id, message_id, reasoning_id)
    except ReasoningNotFoundError as exc:
        raise not_found(404, "reasoning not found", "reasoning_not_found") from exc


async def _hydrate_message_attachment_urls(
    messages: list,
    file_service: UserFileService,
) -> None:
    """Replace stored attachment URLs with fresh presigned URLs when possible."""
    for message in messages:
        metadata = getattr(message, "message_metadata", None)
        if not isinstance(metadata, dict):
            continue

        attachments = metadata.get("attachments")
        if not isinstance(attachments, list):
            continue

        hydrated_attachments = [
            await _hydrate_attachment_url(attachment, file_service) for attachment in attachments
        ]
        message.message_metadata = {**metadata, "attachments": hydrated_attachments}


async def _hydrate_attachment_url(
    attachment: object,
    file_service: UserFileService,
) -> object:
    if not isinstance(attachment, dict):
        return attachment

    file_id = _attachment_file_id(attachment)
    if not file_id:
        return attachment

    try:
        metadata, url = await file_service.create_download_url(file_id)
    except (
        S3ConfigurationError,
        S3StorageError,
        UserFileNotFoundError,
        UserFileObjectNotFoundError,
    ):
        return attachment

    return {
        **attachment,
        "url": url,
        "mediaType": (
            metadata.content_type or attachment.get("mediaType") or "application/octet-stream"
        ),
        "title": metadata.original_filename or attachment.get("title") or "attachment",
        "providerFileId": metadata.id,
    }


def _attachment_file_id(attachment: dict) -> str | None:
    value = (
        attachment.get("providerFileId")
        or attachment.get("provider_file_id")
        or attachment.get("id")
    )
    return str(value) if value else None
