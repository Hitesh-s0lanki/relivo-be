"""Schemas for user file APIs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FileCategory = Literal["image", "document", "file"]


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
