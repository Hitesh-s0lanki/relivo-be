"""Tests for the user file service."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from src.services.user_file_service import (
    EmptyUploadError,
    S3FileSettings,
    UploadTooLargeError,
    UserFileService,
)


class FakeSession:
    """Small async session double for service tests."""

    def __init__(self, record: SimpleNamespace | None = None, *, fail_commit: bool = False) -> None:
        """Initialize the fake session state."""
        self.record = record
        self.fail_commit = fail_commit
        self.added = []
        self.deleted = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshes = 0

    def add(self, metadata) -> None:
        self.added.append(metadata)

    async def commit(self) -> None:
        self.commits += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, _metadata) -> None:
        self.refreshes += 1

    async def get(self, _model, _file_id: str) -> SimpleNamespace | None:
        return self.record

    async def delete(self, metadata) -> None:
        self.deleted.append(metadata)


class FakeS3Client:
    """S3 client double that records object operations."""

    def __init__(self) -> None:
        """Initialize empty call history."""
        self.uploads = []
        self.deletes = []
        self.presign_calls = []

    def upload_fileobj(self, fileobj, bucket: str, key: str, **kwargs) -> None:
        self.uploads.append(
            {
                "body": fileobj.read(),
                "bucket": bucket,
                "key": key,
                "extra_args": kwargs["ExtraArgs"],
            }
        )

    def delete_object(self, **kwargs) -> None:
        self.deletes.append({"bucket": kwargs["Bucket"], "key": kwargs["Key"]})

    def generate_presigned_url(self, operation: str, **kwargs) -> str:
        self.presign_calls.append(
            {
                "operation": operation,
                "params": kwargs["Params"],
                "expires_in": kwargs["ExpiresIn"],
            }
        )
        return f"https://files.example.test/{kwargs['Params']['Key']}"


@pytest.fixture
def settings() -> S3FileSettings:
    """Return deterministic S3 settings for service tests."""
    return S3FileSettings(
        bucket="test-bucket",
        region_name="us-east-1",
        endpoint_url=None,
        key_prefix="uploads",
        presigned_expires_seconds=900,
        max_upload_bytes=16,
        server_side_encryption="aws:kms",
        kms_key_id="kms-key",
    )


def upload_file(filename: str, contents: bytes, content_type: str) -> UploadFile:
    """Build a FastAPI upload object with content-type headers."""
    return UploadFile(
        file=BytesIO(contents),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


@pytest.mark.asyncio
async def test_upload_file_stores_s3_object_and_metadata(settings: S3FileSettings) -> None:
    """Uploading a file should write S3 content and persist metadata."""
    session = FakeSession()
    s3_client = FakeS3Client()
    service = UserFileService(session, settings=settings, s3_client=s3_client)

    metadata = await service.upload_file(
        user_id="user/123",
        upload=upload_file("../report final.pdf", b"hello", "application/pdf"),
    )

    assert metadata in session.added
    assert session.commits == 1
    assert session.refreshes == 1
    assert metadata.user_id == "user/123"
    assert metadata.original_filename == "report final.pdf"
    assert metadata.content_type == "application/pdf"
    assert metadata.file_category == "document"
    assert metadata.size_bytes == 5
    assert metadata.s3_bucket == "test-bucket"
    assert metadata.s3_key == f"uploads/users/user-123/{metadata.id}/report-final.pdf"
    assert s3_client.uploads == [
        {
            "body": b"hello",
            "bucket": "test-bucket",
            "key": metadata.s3_key,
            "extra_args": {
                "ContentType": "application/pdf",
                "Metadata": {"source": "relivo-be-server"},
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": "kms-key",
            },
        }
    ]


@pytest.mark.asyncio
async def test_upload_file_rejects_empty_upload(settings: S3FileSettings) -> None:
    """Empty uploads should fail before S3 or database writes."""
    session = FakeSession()
    s3_client = FakeS3Client()
    service = UserFileService(session, settings=settings, s3_client=s3_client)

    with pytest.raises(EmptyUploadError):
        await service.upload_file(
            user_id="user-123",
            upload=upload_file("empty.txt", b"", "text/plain"),
        )

    assert session.added == []
    assert s3_client.uploads == []


@pytest.mark.asyncio
async def test_upload_file_rejects_oversized_upload(settings: S3FileSettings) -> None:
    """Oversized uploads should fail before S3 or database writes."""
    session = FakeSession()
    s3_client = FakeS3Client()
    service = UserFileService(session, settings=settings, s3_client=s3_client)

    with pytest.raises(UploadTooLargeError) as exc_info:
        await service.upload_file(
            user_id="user-123",
            upload=upload_file("large.txt", b"x" * 17, "text/plain"),
        )

    assert exc_info.value.max_bytes == 16
    assert session.added == []
    assert s3_client.uploads == []


@pytest.mark.asyncio
async def test_upload_file_deletes_s3_object_when_commit_fails(settings: S3FileSettings) -> None:
    """A failed metadata commit should clean up the uploaded S3 object."""
    session = FakeSession(fail_commit=True)
    s3_client = FakeS3Client()
    service = UserFileService(session, settings=settings, s3_client=s3_client)

    with pytest.raises(RuntimeError, match="commit failed"):
        await service.upload_file(
            user_id="user-123",
            upload=upload_file("avatar.png", b"image", "image/png"),
        )

    uploaded_key = s3_client.uploads[0]["key"]
    assert session.rollbacks == 1
    assert s3_client.deletes == [{"bucket": "test-bucket", "key": uploaded_key}]


@pytest.mark.asyncio
async def test_create_download_url_uses_metadata_and_expiry(settings: S3FileSettings) -> None:
    """Download URLs should be generated from stored metadata."""
    record = SimpleNamespace(
        s3_bucket="metadata-bucket",
        s3_key="uploads/users/user-123/file-id/report.pdf",
        original_filename='quarterly "report".pdf',
        content_type="application/pdf",
    )
    session = FakeSession(record)
    s3_client = FakeS3Client()
    service = UserFileService(session, settings=settings, s3_client=s3_client)

    metadata, url = await service.create_download_url("file-id")

    assert metadata is record
    assert url == "https://files.example.test/uploads/users/user-123/file-id/report.pdf"
    assert s3_client.presign_calls == [
        {
            "operation": "get_object",
            "params": {
                "Bucket": "metadata-bucket",
                "Key": "uploads/users/user-123/file-id/report.pdf",
                "ResponseContentDisposition": 'attachment; filename="quarterly-report-.pdf"',
                "ResponseContentType": "application/pdf",
            },
            "expires_in": 900,
        }
    ]


@pytest.mark.asyncio
async def test_create_attachment_response_uses_presigned_url(settings: S3FileSettings) -> None:
    """Attachment responses should expose frontend fields and the stored file id."""
    record = SimpleNamespace(
        id="file-id",
        s3_bucket="metadata-bucket",
        s3_key="uploads/users/user-123/file-id/avatar.png",
        original_filename="avatar.png",
        content_type="image/png",
        size_bytes=123,
    )
    session = FakeSession(record)
    s3_client = FakeS3Client()
    service = UserFileService(session, settings=settings, s3_client=s3_client)

    attachment = await service.create_attachment_response(record)

    assert attachment.model_dump(by_alias=True) == {
        "id": "file-id",
        "url": "https://files.example.test/uploads/users/user-123/file-id/avatar.png",
        "mediaType": "image/png",
        "title": "avatar.png",
        "size": 123,
        "providerFileId": "file-id",
    }


@pytest.mark.asyncio
async def test_delete_file_removes_s3_object_and_metadata(settings: S3FileSettings) -> None:
    """Deleting a file should remove both S3 content and metadata."""
    record = SimpleNamespace(
        s3_bucket="metadata-bucket",
        s3_key="uploads/users/user-123/file-id/avatar.png",
    )
    session = FakeSession(record)
    s3_client = FakeS3Client()
    service = UserFileService(session, settings=settings, s3_client=s3_client)

    await service.delete_file("file-id")

    assert s3_client.deletes == [
        {"bucket": "metadata-bucket", "key": "uploads/users/user-123/file-id/avatar.png"}
    ]
    assert session.deleted == [record]
    assert session.commits == 1
