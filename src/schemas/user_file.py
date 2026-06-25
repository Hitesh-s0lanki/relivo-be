"""Schemas for user file APIs."""

from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

FileCategory = Literal["image", "document", "file"]


class AttachmentInput(BaseModel):
    """Attachment reference accepted by chat and conversation APIs."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    url: str = Field(..., min_length=1)
    media_type: str = Field(
        ...,
        validation_alias=AliasChoices("mediaType", "media_type"),
        serialization_alias="mediaType",
        min_length=1,
    )
    title: str = Field(..., min_length=1, max_length=500)


class UploadedAttachment(AttachmentInput):
    """Frontend-friendly uploaded attachment response."""

    id: str
    size: int = Field(..., ge=0)
    provider_file_id: str = Field(
        ...,
        validation_alias=AliasChoices("providerFileId", "provider_file_id"),
        serialization_alias="providerFileId",
    )


class UploadsData(BaseModel):
    """Data envelope for uploaded attachments."""

    attachments: list[UploadedAttachment]


class UploadsResponse(BaseModel):
    """Response body for the chat upload API."""

    success: bool = True
    data: UploadsData


class UserFileResponse(BaseModel):
    """Uploaded file metadata response body."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    original_filename: str
    content_type: str | None
    file_category: FileCategory
    size_bytes: int
    checksum_sha256: str
    s3_bucket: str
    s3_key: str
    created_at: datetime
    updated_at: datetime


class UserFileDownloadResponse(BaseModel):
    """Response body containing a temporary S3 download URL."""

    file: UserFileResponse
    url: str
    expires_in_seconds: int = Field(..., ge=1)
