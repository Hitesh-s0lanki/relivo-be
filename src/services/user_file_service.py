"""S3-backed user file service."""

import base64
import hashlib
import os
import re
from dataclasses import dataclass
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import Any

import anyio
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import UserFile
from src.models.common import uuid_str
from src.schemas.user_file import FileCategory, UploadedAttachment

DOCUMENT_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".json",
    ".md",
    ".pdf",
    ".ppt",
    ".pptx",
    ".rtf",
    ".txt",
    ".xls",
    ".xlsx",
    ".xml",
}
DOCUMENT_CONTENT_TYPES = {
    "application/json",
    "application/msword",
    "application/pdf",
    "application/rtf",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/xml",
    "text/csv",
    "text/markdown",
    "text/plain",
    "text/xml",
}
DEFAULT_MAX_UPLOAD_MB = 25
DEFAULT_PRESIGNED_EXPIRES_SECONDS = 3600


class UserFileNotFoundError(Exception):
    """Raised when a user file cannot be found."""


class UserFileObjectNotFoundError(Exception):
    """Raised when file metadata exists but the S3 object is missing."""


class EmptyUploadError(Exception):
    """Raised when an uploaded file has no content."""


class UploadTooLargeError(Exception):
    """Raised when an uploaded file exceeds the configured size limit."""

    def __init__(self, max_bytes: int) -> None:
        """Initialize with the configured maximum byte size."""
        super().__init__(max_bytes)
        self.max_bytes = max_bytes


class S3ConfigurationError(Exception):
    """Raised when S3 configuration is incomplete."""


class S3StorageError(Exception):
    """Raised when an S3 operation fails."""


@dataclass(frozen=True)
class S3FileSettings:
    """S3 settings for user file storage."""

    bucket: str
    region_name: str
    endpoint_url: str | None
    key_prefix: str
    presigned_expires_seconds: int
    max_upload_bytes: int
    server_side_encryption: str | None
    kms_key_id: str | None


def get_s3_file_settings() -> S3FileSettings:
    """Read S3 file storage settings from environment variables."""
    bucket = os.getenv("AWS_S3_BUCKET") or os.getenv("S3_BUCKET_NAME")
    if not bucket:
        raise S3ConfigurationError("AWS_S3_BUCKET is required for file storage")

    max_upload_mb = int(os.getenv("AWS_S3_MAX_UPLOAD_MB", str(DEFAULT_MAX_UPLOAD_MB)))
    expires = int(
        os.getenv(
            "AWS_S3_PRESIGNED_EXPIRES_SECONDS",
            str(DEFAULT_PRESIGNED_EXPIRES_SECONDS),
        )
    )
    return S3FileSettings(
        bucket=bucket,
        region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        endpoint_url=os.getenv("AWS_S3_ENDPOINT_URL"),
        key_prefix=os.getenv("AWS_S3_KEY_PREFIX", "user-files").strip("/"),
        presigned_expires_seconds=expires,
        max_upload_bytes=max_upload_mb * 1024 * 1024,
        server_side_encryption=os.getenv("AWS_S3_SERVER_SIDE_ENCRYPTION"),
        kms_key_id=os.getenv("AWS_S3_KMS_KEY_ID"),
    )


class UserFileService:
    """Manage user file metadata and S3 objects."""

    def __init__(
        self,
        session: AsyncSession,
        settings: S3FileSettings | None = None,
        s3_client: Any | None = None,
    ) -> None:
        """Initialize the service with a database session and S3 client."""
        self.session = session
        self._settings = settings
        self._s3_client = s3_client
        self._s3_client_was_injected = s3_client is not None
        self._bucket_region_name: str | None = None
        self._bucket_region_s3_client: Any | None = None

    @property
    def settings(self) -> S3FileSettings:
        """Return S3 file settings, loading them only when needed."""
        if self._settings is None:
            self._settings = get_s3_file_settings()
        return self._settings

    @property
    def s3_client(self) -> Any:
        """Return a cached S3 client, creating it only when needed."""
        if self._s3_client is None:
            self._s3_client = self._build_s3_client()
        return self._s3_client

    async def upload_file(self, user_id: str, upload: UploadFile) -> UserFile:
        """Upload a file to S3 and store its metadata."""
        file_id = uuid_str()
        contents = await upload.read(self.settings.max_upload_bytes + 1)
        await upload.close()

        if not contents:
            raise EmptyUploadError
        if len(contents) > self.settings.max_upload_bytes:
            raise UploadTooLargeError(self.settings.max_upload_bytes)

        original_filename = Path(upload.filename or "upload").name
        safe_filename = _sanitize_filename(original_filename)
        s3_key = self._build_s3_key(user_id=user_id, file_id=file_id, filename=safe_filename)
        content_type = upload.content_type or "application/octet-stream"
        checksum = hashlib.sha256(contents).hexdigest()

        metadata = UserFile(
            id=file_id,
            user_id=user_id,
            original_filename=original_filename,
            content_type=content_type,
            file_category=_classify_file(original_filename, content_type),
            size_bytes=len(contents),
            checksum_sha256=checksum,
            s3_bucket=self.settings.bucket,
            s3_key=s3_key,
        )

        try:
            await self._upload_object(contents, s3_key, content_type)
            await self._ensure_object_exists(self.settings.bucket, s3_key)
        except (BotoCoreError, ClientError) as exc:
            raise S3StorageError("failed to upload file to S3") from exc
        except UserFileObjectNotFoundError as exc:
            await self._delete_uploaded_object_best_effort(s3_key)
            raise S3StorageError("uploaded file is not readable from S3") from exc

        self.session.add(metadata)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            await self._delete_uploaded_object_best_effort(s3_key)
            raise

        await self.session.refresh(metadata)
        return metadata

    async def list_user_files(
        self,
        user_id: str,
        file_category: FileCategory | None = None,
    ) -> list[UserFile]:
        """List files belonging to a user."""
        statement = select(UserFile).where(UserFile.user_id == user_id)
        if file_category:
            statement = statement.where(UserFile.file_category == file_category)
        result = await self.session.execute(statement.order_by(UserFile.created_at.desc()))
        return list(result.scalars().all())

    async def get_file(self, file_id: str) -> UserFile:
        """Get file metadata by id."""
        metadata = await self.session.get(UserFile, file_id)
        if metadata is None:
            raise UserFileNotFoundError(file_id)
        return metadata

    async def create_download_url(self, file_id: str) -> tuple[UserFile, str]:
        """Create a temporary presigned URL for a stored file."""
        metadata = await self.get_file(file_id)
        url = await self.create_presigned_download_url(metadata)
        return metadata, url

    async def create_attachment_response(self, metadata: UserFile) -> UploadedAttachment:
        """Create a frontend attachment reference for an uploaded file."""
        return UploadedAttachment(
            id=metadata.id,
            url=await self.create_presigned_download_url(metadata),
            mediaType=metadata.content_type or "application/octet-stream",
            title=metadata.original_filename,
            size=metadata.size_bytes,
            providerFileId=metadata.id,
        )

    async def create_data_url(self, file_id: str) -> tuple[UserFile, str]:
        """Read a stored file from S3 and return a base64 data URL."""
        metadata, contents = await self.read_file_bytes(file_id)
        media_type = metadata.content_type or "application/octet-stream"
        encoded = base64.b64encode(contents).decode("ascii")
        return metadata, f"data:{media_type};base64,{encoded}"

    async def read_file_bytes(self, file_id: str) -> tuple[UserFile, bytes]:
        """Read a stored file from S3 and return its raw bytes."""
        metadata = await self.get_file(file_id)
        try:
            await self._ensure_object_exists(metadata.s3_bucket, metadata.s3_key)
            response = await anyio.to_thread.run_sync(
                partial(
                    (await self._s3_client_for_bucket()).get_object,
                    Bucket=metadata.s3_bucket,
                    Key=metadata.s3_key,
                )
            )
            contents = await anyio.to_thread.run_sync(response["Body"].read)
        except UserFileObjectNotFoundError:
            raise
        except ClientError as exc:
            if _is_missing_s3_object_error(exc):
                raise UserFileObjectNotFoundError(file_id) from exc
            raise S3StorageError("failed to read file from S3") from exc
        except (BotoCoreError, KeyError) as exc:
            raise S3StorageError("failed to read file from S3") from exc

        return metadata, contents

    async def create_presigned_download_url(self, metadata: UserFile) -> str:
        """Create a temporary presigned URL for stored file metadata."""
        params = {
            "Bucket": metadata.s3_bucket,
            "Key": metadata.s3_key,
            "ResponseContentDisposition": _content_disposition(metadata.original_filename),
        }
        if metadata.content_type:
            params["ResponseContentType"] = metadata.content_type

        try:
            await self._ensure_object_exists(metadata.s3_bucket, metadata.s3_key)
            url = await anyio.to_thread.run_sync(
                partial(
                    (await self._s3_client_for_bucket()).generate_presigned_url,
                    "get_object",
                    Params=params,
                    ExpiresIn=self.settings.presigned_expires_seconds,
                )
            )
        except UserFileObjectNotFoundError:
            raise
        except (BotoCoreError, ClientError) as exc:
            raise S3StorageError("failed to create S3 download URL") from exc

        return url

    async def delete_file(self, file_id: str) -> None:
        """Delete a file from S3 and remove its metadata."""
        metadata = await self.get_file(file_id)
        try:
            await anyio.to_thread.run_sync(
                partial(
                    (await self._s3_client_for_bucket()).delete_object,
                    Bucket=metadata.s3_bucket,
                    Key=metadata.s3_key,
                )
            )
        except (BotoCoreError, ClientError) as exc:
            raise S3StorageError("failed to delete file from S3") from exc

        await self.session.delete(metadata)
        await self.session.commit()

    def _build_s3_client(self) -> Any:
        return self._build_s3_client_for_region(self.settings.region_name)

    def _build_s3_client_for_region(self, region_name: str) -> Any:
        session = boto3.session.Session(region_name=region_name)
        kwargs: dict[str, str] = {}
        if self.settings.endpoint_url:
            kwargs["endpoint_url"] = self.settings.endpoint_url
        return session.client("s3", region_name=region_name, **kwargs)

    async def _s3_client_for_bucket(self) -> Any:
        if self._s3_client_was_injected or self.settings.endpoint_url:
            return self.s3_client

        region_name = await self._resolve_bucket_region_name()
        if region_name == self.settings.region_name:
            return self.s3_client

        if self._bucket_region_s3_client is None:
            self._bucket_region_s3_client = self._build_s3_client_for_region(region_name)
        return self._bucket_region_s3_client

    async def _resolve_bucket_region_name(self) -> str:
        if self._bucket_region_name is not None:
            return self._bucket_region_name

        try:
            lookup_client = self._build_s3_client_for_region("us-east-1")
            response = await anyio.to_thread.run_sync(
                partial(
                    lookup_client.get_bucket_location,
                    Bucket=self.settings.bucket,
                )
            )
        except (BotoCoreError, ClientError):
            self._bucket_region_name = self.settings.region_name
            return self._bucket_region_name

        self._bucket_region_name = _normalize_bucket_location(response.get("LocationConstraint"))
        return self._bucket_region_name

    def _build_s3_key(self, *, user_id: str, file_id: str, filename: str) -> str:
        user_segment = _sanitize_key_segment(user_id)
        segments = [self.settings.key_prefix, "users", user_segment, file_id, filename]
        return "/".join(segment for segment in segments if segment)

    async def _upload_object(self, contents: bytes, s3_key: str, content_type: str) -> None:
        extra_args = {
            "ContentType": content_type,
            "Metadata": {"source": "relivo-be-server"},
        }
        if self.settings.server_side_encryption:
            extra_args["ServerSideEncryption"] = self.settings.server_side_encryption
        if self.settings.kms_key_id:
            extra_args["SSEKMSKeyId"] = self.settings.kms_key_id

        await anyio.to_thread.run_sync(
            partial(
                (await self._s3_client_for_bucket()).upload_fileobj,
                BytesIO(contents),
                self.settings.bucket,
                s3_key,
                ExtraArgs=extra_args,
            )
        )

    async def _ensure_object_exists(self, bucket: str, s3_key: str) -> None:
        try:
            await anyio.to_thread.run_sync(
                partial(
                    (await self._s3_client_for_bucket()).head_object,
                    Bucket=bucket,
                    Key=s3_key,
                )
            )
        except ClientError as exc:
            if _is_missing_s3_object_error(exc):
                raise UserFileObjectNotFoundError(s3_key) from exc
            raise

    async def _delete_uploaded_object_best_effort(self, s3_key: str) -> None:
        try:
            await anyio.to_thread.run_sync(
                partial(
                    (await self._s3_client_for_bucket()).delete_object,
                    Bucket=self.settings.bucket,
                    Key=s3_key,
                )
            )
        except (BotoCoreError, ClientError):
            pass


def _classify_file(filename: str, content_type: str | None) -> FileCategory:
    normalized_type = (content_type or "").split(";")[0].strip().lower()
    if normalized_type.startswith("image/"):
        return "image"
    if normalized_type in DOCUMENT_CONTENT_TYPES:
        return "document"
    if Path(filename).suffix.lower() in DOCUMENT_EXTENSIONS:
        return "document"
    return "file"


def _sanitize_filename(filename: str) -> str:
    base = Path(filename).name.strip() or "upload"
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip(".-")
    return sanitized[:180] or "upload"


def _sanitize_key_segment(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._=-]+", "-", value.strip()).strip(".-")
    return sanitized[:180] or "unknown-user"


def _content_disposition(filename: str) -> str:
    return f'attachment; filename="{_sanitize_filename(filename)}"'


def _normalize_bucket_location(location_constraint: str | None) -> str:
    if not location_constraint:
        return "us-east-1"
    if location_constraint == "EU":
        return "eu-west-1"
    return location_constraint


def _is_missing_s3_object_error(exc: ClientError) -> bool:
    error = exc.response.get("Error", {})
    code = str(error.get("Code", ""))
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404
