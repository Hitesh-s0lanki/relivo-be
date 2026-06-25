"""User file HTTP controller."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db_session
from src.schemas.chat import ChatErrorResponse
from src.schemas.user_file import (
    FileCategory,
    PresignedAttachmentData,
    PresignedAttachmentResponse,
    UploadsData,
    UploadsResponse,
    UserFileDownloadResponse,
    UserFileResponse,
)
from src.services.conversation_service import ConversationNotFoundError, ConversationService
from src.services.user_file_service import (
    EmptyUploadError,
    S3ConfigurationError,
    S3StorageError,
    UploadTooLargeError,
    UserFileNotFoundError,
    UserFileService,
)
from src.utils.error_response import build_error_response

router = APIRouter(prefix="/files", tags=["Files"])
ai_router = APIRouter(prefix="/ai", tags=["AI Uploads"])


def get_user_file_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserFileService:
    """Resolve the user file service dependency."""
    return UserFileService(session)


UserFileServiceDependency = Annotated[UserFileService, Depends(get_user_file_service)]


def get_upload_conversation_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationService:
    """Resolve the conversation service dependency for upload ownership lookup."""
    return ConversationService(session)


UploadConversationServiceDependency = Annotated[
    ConversationService,
    Depends(get_upload_conversation_service),
]


@ai_router.post(
    "/uploads",
    response_model=UploadsResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "Upload request is invalid.", "model": ChatErrorResponse},
        404: {"description": "Conversation was not found.", "model": ChatErrorResponse},
        413: {"description": "Uploaded file is too large.", "model": ChatErrorResponse},
        500: {"description": "S3 file storage failed.", "model": ChatErrorResponse},
    },
)
async def upload_ai_attachments(
    service: UserFileServiceDependency,
    conversation_service: UploadConversationServiceDependency,
    files: Annotated[list[UploadFile], File(alias="files[]")],
    user_id: Annotated[str | None, Form(alias="userId", min_length=1, max_length=200)] = None,
    conversation_id: Annotated[
        str | None,
        Form(alias="conversationId", min_length=1, max_length=200),
    ] = None,
) -> UploadsResponse:
    """Upload one or more chat attachments to S3 and return attachment references."""
    if not files:
        raise _http_error(400, "at least one file is required", "missing_upload_files")

    try:
        resolved_user_id = await _resolve_upload_user_id(
            user_id=user_id,
            conversation_id=conversation_id,
            conversation_service=conversation_service,
        )
        attachments = []
        for upload in files:
            metadata = await service.upload_file(user_id=resolved_user_id, upload=upload)
            attachments.append(await service.create_attachment_response(metadata))
    except ConversationNotFoundError as exc:
        raise _http_error(404, "conversation not found", "conversation_not_found") from exc
    except EmptyUploadError as exc:
        raise _http_error(400, "uploaded file cannot be empty", "empty_upload") from exc
    except UploadTooLargeError as exc:
        max_mb = exc.max_bytes // (1024 * 1024)
        raise _http_error(413, f"uploaded file exceeds {max_mb} MB", "upload_too_large") from exc
    except S3ConfigurationError as exc:
        raise _http_error(500, "S3 file storage is not configured", "s3_not_configured") from exc
    except S3StorageError as exc:
        raise _http_error(500, "S3 file storage failed", "s3_storage_failed") from exc

    return UploadsResponse(data=UploadsData(attachments=attachments))


@ai_router.get(
    "/uploads/{file_id}/presigned-url",
    response_model=PresignedAttachmentResponse,
    responses={
        404: {"description": "File not found.", "model": ChatErrorResponse},
        500: {"description": "S3 file storage failed.", "model": ChatErrorResponse},
    },
)
async def create_ai_attachment_presigned_url(
    file_id: str,
    service: UserFileServiceDependency,
) -> PresignedAttachmentResponse:
    """Create a fresh presigned URL for one uploaded chat attachment."""
    try:
        metadata = await service.get_file(file_id)
        attachment = await service.create_attachment_response(metadata)
    except UserFileNotFoundError as exc:
        raise _http_error(404, "file not found", "file_not_found") from exc
    except S3ConfigurationError as exc:
        raise _http_error(500, "S3 file storage is not configured", "s3_not_configured") from exc
    except S3StorageError as exc:
        raise _http_error(500, "S3 file storage failed", "s3_storage_failed") from exc

    return PresignedAttachmentResponse(
        data=PresignedAttachmentData(
            attachment=attachment,
            expires_in_seconds=service.settings.presigned_expires_seconds,
        )
    )


@router.post(
    "",
    response_model=UserFileResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        413: {"description": "Uploaded file is too large.", "model": ChatErrorResponse},
        500: {"description": "S3 file storage failed.", "model": ChatErrorResponse},
    },
)
async def upload_user_file(
    service: UserFileServiceDependency,
    user_id: Annotated[str, Form(min_length=1, max_length=200)],
    file: Annotated[UploadFile, File()],
) -> UserFileResponse:
    """Upload a user file to S3 and save its metadata."""
    try:
        return await service.upload_file(user_id=user_id, upload=file)
    except EmptyUploadError as exc:
        raise _http_error(400, "uploaded file cannot be empty", "empty_upload") from exc
    except UploadTooLargeError as exc:
        max_mb = exc.max_bytes // (1024 * 1024)
        raise _http_error(413, f"uploaded file exceeds {max_mb} MB", "upload_too_large") from exc
    except S3ConfigurationError as exc:
        raise _http_error(500, "S3 file storage is not configured", "s3_not_configured") from exc
    except S3StorageError as exc:
        raise _http_error(500, "S3 file storage failed", "s3_storage_failed") from exc


@router.get("/users/{user_id}", response_model=list[UserFileResponse])
async def list_user_files(
    user_id: str,
    service: UserFileServiceDependency,
    file_category: Annotated[FileCategory | None, Query()] = None,
) -> list[UserFileResponse]:
    """List all files belonging to a user."""
    return await service.list_user_files(user_id=user_id, file_category=file_category)


@router.get("/{file_id}", response_model=UserFileResponse)
async def get_user_file(
    file_id: str,
    service: UserFileServiceDependency,
) -> UserFileResponse:
    """Get metadata for a user file."""
    try:
        return await service.get_file(file_id)
    except UserFileNotFoundError as exc:
        raise _http_error(404, "file not found", "file_not_found") from exc


@router.get(
    "/{file_id}/download",
    response_model=UserFileDownloadResponse,
    responses={
        404: {"description": "File not found.", "model": ChatErrorResponse},
        500: {"description": "S3 file storage failed.", "model": ChatErrorResponse},
    },
)
async def create_user_file_download_url(
    file_id: str,
    service: UserFileServiceDependency,
) -> UserFileDownloadResponse:
    """Create a temporary presigned URL for downloading a file."""
    try:
        metadata, url = await service.create_download_url(file_id)
    except UserFileNotFoundError as exc:
        raise _http_error(404, "file not found", "file_not_found") from exc
    except S3ConfigurationError as exc:
        raise _http_error(500, "S3 file storage is not configured", "s3_not_configured") from exc
    except S3StorageError as exc:
        raise _http_error(500, "S3 file storage failed", "s3_storage_failed") from exc

    return UserFileDownloadResponse(
        file=metadata,
        url=url,
        expires_in_seconds=service.settings.presigned_expires_seconds,
    )


@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"description": "File not found.", "model": ChatErrorResponse},
        500: {"description": "S3 file storage failed.", "model": ChatErrorResponse},
    },
)
async def delete_user_file(
    file_id: str,
    service: UserFileServiceDependency,
) -> None:
    """Delete a user file from S3 and metadata storage."""
    try:
        await service.delete_file(file_id)
    except UserFileNotFoundError as exc:
        raise _http_error(404, "file not found", "file_not_found") from exc
    except S3ConfigurationError as exc:
        raise _http_error(500, "S3 file storage is not configured", "s3_not_configured") from exc
    except S3StorageError as exc:
        raise _http_error(500, "S3 file storage failed", "s3_storage_failed") from exc


def _http_error(status_code: int, message: str, error_tag: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=build_error_response(
            status=status_code,
            message=message,
            error_tag=error_tag,
        ).model_dump(),
    )


async def _resolve_upload_user_id(
    *,
    user_id: str | None,
    conversation_id: str | None,
    conversation_service: ConversationService,
) -> str:
    if user_id:
        return user_id
    if conversation_id:
        conversation = await conversation_service.get_conversation(conversation_id)
        return conversation.user_id
    raise _http_error(400, "userId or conversationId is required", "missing_upload_owner")
