"""Tests for user file routes."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.controllers.user_file_controller import (
    get_upload_conversation_service,
    get_user_file_service,
)
from src.main import create_app
from src.schemas.user_file import UploadedAttachment
from src.services.conversation_service import ConversationNotFoundError
from src.services.user_file_service import EmptyUploadError, UserFileNotFoundError


def now() -> datetime:
    """Return a stable UTC timestamp for fake records."""
    return datetime.now(UTC)


class FakeUserFileService:
    """In-memory file service for route tests."""

    def __init__(self) -> None:
        """Initialize empty fake file storage."""
        self.files: dict[str, SimpleNamespace] = {}
        self.settings = SimpleNamespace(presigned_expires_seconds=600)

    async def upload_file(self, user_id: str, upload) -> SimpleNamespace:
        contents = await upload.read()
        if not contents:
            raise EmptyUploadError
        file_id = str(uuid4())
        metadata = SimpleNamespace(
            id=file_id,
            user_id=user_id,
            original_filename=upload.filename,
            content_type=upload.content_type,
            file_category="image" if upload.content_type.startswith("image/") else "file",
            size_bytes=len(contents),
            checksum_sha256="0" * 64,
            s3_bucket="test-bucket",
            s3_key=f"user-files/users/{user_id}/{file_id}/{upload.filename}",
            created_at=now(),
            updated_at=now(),
        )
        self.files[file_id] = metadata
        return metadata

    async def list_user_files(
        self,
        user_id: str,
        file_category: str | None = None,
    ) -> list[SimpleNamespace]:
        records = [metadata for metadata in self.files.values() if metadata.user_id == user_id]
        if file_category:
            records = [metadata for metadata in records if metadata.file_category == file_category]
        return records

    async def get_file(self, file_id: str) -> SimpleNamespace:
        metadata = self.files.get(file_id)
        if metadata is None:
            raise UserFileNotFoundError(file_id)
        return metadata

    async def create_download_url(self, file_id: str) -> tuple[SimpleNamespace, str]:
        metadata = await self.get_file(file_id)
        return metadata, f"https://example.test/{metadata.s3_key}"

    async def create_attachment_response(self, metadata: SimpleNamespace) -> UploadedAttachment:
        return UploadedAttachment(
            id=metadata.id,
            url=f"https://example.test/{metadata.s3_key}",
            mediaType=metadata.content_type,
            title=metadata.original_filename,
            size=metadata.size_bytes,
            providerFileId=metadata.id,
        )

    async def delete_file(self, file_id: str) -> None:
        if file_id not in self.files:
            raise UserFileNotFoundError(file_id)
        del self.files[file_id]


class FakeConversationService:
    """In-memory conversation service for upload ownership lookup."""

    def __init__(self) -> None:
        """Initialize fake conversations."""
        self.conversations = {
            "conversation-123": SimpleNamespace(id="conversation-123", user_id="user-123")
        }

    async def get_conversation(self, conversation_id: str) -> SimpleNamespace:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        return conversation


@pytest.mark.asyncio
async def test_upload_and_list_user_files() -> None:
    """Files can be uploaded and then listed by user id."""
    app = create_app()
    service = FakeUserFileService()
    app.dependency_overrides[get_user_file_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        upload_response = await client.post(
            "/files",
            data={"user_id": "user-123"},
            files={"file": ("avatar.png", b"image-bytes", "image/png")},
        )
        list_response = await client.get("/files/users/user-123")

    assert upload_response.status_code == 201
    uploaded = upload_response.json()
    assert uploaded["user_id"] == "user-123"
    assert uploaded["original_filename"] == "avatar.png"
    assert uploaded["file_category"] == "image"
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [uploaded["id"]]


@pytest.mark.asyncio
async def test_upload_ai_attachments_returns_frontend_attachment_shape() -> None:
    """AI upload route should upload multiple files and return attachment references."""
    app = create_app()
    file_service = FakeUserFileService()
    app.dependency_overrides[get_user_file_service] = lambda: file_service
    app.dependency_overrides[get_upload_conversation_service] = lambda: FakeConversationService()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/ai/uploads",
            data={"conversationId": "conversation-123"},
            files=[
                ("files[]", ("avatar.png", b"image-bytes", "image/png")),
                ("files[]", ("notes.txt", b"hello", "text/plain")),
            ],
        )

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert len(body["data"]["attachments"]) == 2
    assert body["data"]["attachments"][0] == {
        "id": body["data"]["attachments"][0]["id"],
        "url": (
            "https://example.test/user-files/users/user-123/"
            f"{body['data']['attachments'][0]['id']}/avatar.png"
        ),
        "mediaType": "image/png",
        "title": "avatar.png",
        "size": len(b"image-bytes"),
        "providerFileId": body["data"]["attachments"][0]["id"],
    }


@pytest.mark.asyncio
async def test_create_ai_attachment_presigned_url() -> None:
    """AI route returns a fresh presigned URL from a provider file id."""
    app = create_app()
    file_service = FakeUserFileService()
    app.dependency_overrides[get_user_file_service] = lambda: file_service
    app.dependency_overrides[get_upload_conversation_service] = lambda: FakeConversationService()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        upload_response = await client.post(
            "/ai/uploads",
            data={"conversationId": "conversation-123"},
            files=[("files[]", ("avatar.png", b"image-bytes", "image/png"))],
        )
        file_id = upload_response.json()["data"]["attachments"][0]["providerFileId"]
        response = await client.get(f"/ai/uploads/{file_id}/presigned-url")

    body = response.json()
    assert response.status_code == 200
    assert body == {
        "success": True,
        "data": {
            "attachment": {
                "id": file_id,
                "url": f"https://example.test/user-files/users/user-123/{file_id}/avatar.png",
                "mediaType": "image/png",
                "title": "avatar.png",
                "size": len(b"image-bytes"),
                "providerFileId": file_id,
            },
            "expiresInSeconds": 600,
        },
    }


@pytest.mark.asyncio
async def test_create_user_file_download_url() -> None:
    """Download route returns file metadata and a presigned URL."""
    app = create_app()
    service = FakeUserFileService()
    app.dependency_overrides[get_user_file_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        upload_response = await client.post(
            "/files",
            data={"user_id": "user-123"},
            files={"file": ("report.pdf", b"pdf-bytes", "application/pdf")},
        )
        file_id = upload_response.json()["id"]
        download_response = await client.get(f"/files/{file_id}/download")

    assert download_response.status_code == 200
    body = download_response.json()
    assert body["file"]["id"] == file_id
    assert body["url"].startswith("https://example.test/user-files/users/user-123/")
    assert body["expires_in_seconds"] == 600


@pytest.mark.asyncio
async def test_get_user_file_not_found_uses_standard_error_response() -> None:
    """Missing file metadata should use the standard error response."""
    app = create_app()
    app.dependency_overrides[get_user_file_service] = lambda: FakeUserFileService()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/files/missing")

    assert response.status_code == 404
    assert response.json() == {
        "status": 404,
        "message": "file not found",
        "error_tag": "file_not_found",
    }


@pytest.mark.asyncio
async def test_delete_user_file_removes_metadata() -> None:
    """Delete route removes a file record."""
    app = create_app()
    service = FakeUserFileService()
    app.dependency_overrides[get_user_file_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        upload_response = await client.post(
            "/files",
            data={"user_id": "user-123"},
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        file_id = upload_response.json()["id"]
        delete_response = await client.delete(f"/files/{file_id}")
        get_response = await client.get(f"/files/{file_id}")

    assert delete_response.status_code == 204
    assert get_response.status_code == 404
