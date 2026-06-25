"""Tests for conversation routes."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.controllers.conversation_controller import (
    get_conversation_service,
    get_conversation_user_file_service,
)
from src.main import create_app
from src.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
    MessageUpdate,
    ReasoningCreate,
    ReasoningUpdate,
    ToolCallCreate,
    ToolCallUpdate,
)
from src.services.conversation_service import (
    ConversationNotFoundError,
    MessageNotFoundError,
    ReasoningNotFoundError,
    ToolCallNotFoundError,
)


def now() -> datetime:
    """Return a stable UTC timestamp for fake records."""
    return datetime.now(UTC)


class FakeConversationService:
    """In-memory conversation service for route tests."""

    def __init__(self) -> None:
        """Initialize empty fake storage."""
        self.conversations: dict[str, SimpleNamespace] = {}
        self.messages: dict[str, list[SimpleNamespace]] = {}

    async def list_conversations(self, user_id: str | None = None) -> list[SimpleNamespace]:
        conversations = list(self.conversations.values())
        if user_id:
            return [
                conversation for conversation in conversations if conversation.user_id == user_id
            ]
        return conversations

    async def create_conversation(self, payload: ConversationCreate) -> SimpleNamespace:
        conversation_id = str(uuid4())
        conversation = SimpleNamespace(
            id=conversation_id,
            user_id=payload.user_id,
            title=payload.title,
            created_at=now(),
            updated_at=now(),
            messages=[],
        )
        self.conversations[conversation_id] = conversation
        self.messages[conversation_id] = []
        return conversation

    async def get_conversation_with_messages(self, conversation_id: str) -> SimpleNamespace:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        conversation.messages = self.messages[conversation_id]
        return conversation

    async def update_conversation(
        self,
        conversation_id: str,
        payload: ConversationUpdate,
    ) -> SimpleNamespace:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        if "title" in payload.model_fields_set:
            conversation.title = payload.title
        conversation.updated_at = now()
        return conversation

    async def delete_conversation(self, conversation_id: str) -> None:
        if conversation_id not in self.conversations:
            raise ConversationNotFoundError(conversation_id)
        del self.conversations[conversation_id]
        del self.messages[conversation_id]

    async def list_messages(self, conversation_id: str) -> list[SimpleNamespace]:
        if conversation_id not in self.conversations:
            raise ConversationNotFoundError(conversation_id)
        return self.messages[conversation_id]

    async def create_message(
        self,
        conversation_id: str,
        payload: MessageCreate,
    ) -> SimpleNamespace:
        if conversation_id not in self.conversations:
            raise ConversationNotFoundError(conversation_id)
        message = SimpleNamespace(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role=payload.role,
            text=payload.text,
            tool_calls=[self._tool_call(tool_call) for tool_call in payload.tool_calls],
            reasoning_entries=[
                self._reasoning_entry(reasoning) for reasoning in payload.reasoning_entries
            ],
            message_metadata=payload.metadata_with_attachments(),
            created_at=now(),
            updated_at=now(),
        )
        for tool_call in message.tool_calls:
            tool_call.message_id = message.id
        for reasoning_entry in message.reasoning_entries:
            reasoning_entry.message_id = message.id
        self.messages[conversation_id].append(message)
        return message

    async def get_message(self, conversation_id: str, message_id: str) -> SimpleNamespace:
        for message in self.messages.get(conversation_id, []):
            if message.id == message_id:
                return message
        raise MessageNotFoundError(message_id)

    async def update_message(
        self,
        conversation_id: str,
        message_id: str,
        payload: MessageUpdate,
    ) -> SimpleNamespace:
        message = await self.get_message(conversation_id, message_id)
        update_data = payload.model_dump(exclude_unset=True)
        if "metadata" in update_data or "attachments" in update_data:
            update_data.pop("metadata", None)
            update_data.pop("attachments", None)
            message_metadata = (
                payload.metadata
                if "metadata" in payload.model_fields_set
                else message.message_metadata
            )
            if "attachments" in payload.model_fields_set:
                message_metadata = dict(message_metadata or {})
                message_metadata["attachments"] = [
                    attachment.model_dump(by_alias=True) for attachment in payload.attachments or []
                ]
            update_data["message_metadata"] = message_metadata
        for field, value in update_data.items():
            setattr(message, field, value)
        message.updated_at = now()
        return message

    async def delete_message(self, conversation_id: str, message_id: str) -> None:
        messages = self.messages.get(conversation_id, [])
        for index, message in enumerate(messages):
            if message.id == message_id:
                del messages[index]
                return
        raise MessageNotFoundError(message_id)

    async def list_tool_calls(self, conversation_id: str, message_id: str) -> list[SimpleNamespace]:
        message = await self.get_message(conversation_id, message_id)
        return message.tool_calls

    async def create_tool_call(
        self,
        conversation_id: str,
        message_id: str,
        payload: ToolCallCreate,
    ) -> SimpleNamespace:
        message = await self.get_message(conversation_id, message_id)
        tool_call = self._tool_call(payload)
        tool_call.message_id = message_id
        message.tool_calls.append(tool_call)
        return tool_call

    async def get_tool_call(
        self,
        conversation_id: str,
        message_id: str,
        tool_call_id: str,
    ) -> SimpleNamespace:
        message = await self.get_message(conversation_id, message_id)
        for tool_call in message.tool_calls:
            if tool_call.id == tool_call_id:
                return tool_call
        raise ToolCallNotFoundError(tool_call_id)

    async def update_tool_call(
        self,
        conversation_id: str,
        message_id: str,
        tool_call_id: str,
        payload: ToolCallUpdate,
    ) -> SimpleNamespace:
        tool_call = await self.get_tool_call(conversation_id, message_id, tool_call_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(tool_call, field, value)
        tool_call.updated_at = now()
        return tool_call

    async def delete_tool_call(
        self,
        conversation_id: str,
        message_id: str,
        tool_call_id: str,
    ) -> None:
        message = await self.get_message(conversation_id, message_id)
        for index, tool_call in enumerate(message.tool_calls):
            if tool_call.id == tool_call_id:
                del message.tool_calls[index]
                return
        raise ToolCallNotFoundError(tool_call_id)

    async def list_reasoning_entries(
        self,
        conversation_id: str,
        message_id: str,
    ) -> list[SimpleNamespace]:
        message = await self.get_message(conversation_id, message_id)
        return message.reasoning_entries

    async def create_reasoning_entry(
        self,
        conversation_id: str,
        message_id: str,
        payload: ReasoningCreate,
    ) -> SimpleNamespace:
        message = await self.get_message(conversation_id, message_id)
        reasoning = self._reasoning_entry(payload)
        reasoning.message_id = message_id
        message.reasoning_entries.append(reasoning)
        return reasoning

    async def get_reasoning_entry(
        self,
        conversation_id: str,
        message_id: str,
        reasoning_id: str,
    ) -> SimpleNamespace:
        message = await self.get_message(conversation_id, message_id)
        for reasoning in message.reasoning_entries:
            if reasoning.id == reasoning_id:
                return reasoning
        raise ReasoningNotFoundError(reasoning_id)

    async def update_reasoning_entry(
        self,
        conversation_id: str,
        message_id: str,
        reasoning_id: str,
        payload: ReasoningUpdate,
    ) -> SimpleNamespace:
        reasoning = await self.get_reasoning_entry(conversation_id, message_id, reasoning_id)
        update_data = payload.model_dump(exclude_unset=True)
        if "metadata" in update_data:
            update_data["reasoning_metadata"] = update_data.pop("metadata")
        for field, value in update_data.items():
            setattr(reasoning, field, value)
        reasoning.updated_at = now()
        return reasoning

    async def delete_reasoning_entry(
        self,
        conversation_id: str,
        message_id: str,
        reasoning_id: str,
    ) -> None:
        message = await self.get_message(conversation_id, message_id)
        for index, reasoning in enumerate(message.reasoning_entries):
            if reasoning.id == reasoning_id:
                del message.reasoning_entries[index]
                return
        raise ReasoningNotFoundError(reasoning_id)

    @staticmethod
    def _tool_call(payload: ToolCallCreate) -> SimpleNamespace:
        return SimpleNamespace(
            id=str(uuid4()),
            message_id="",
            tool_call_id=payload.tool_call_id,
            name=payload.name,
            arguments=payload.arguments,
            result=payload.result,
            status=payload.status,
            sequence=payload.sequence,
            created_at=now(),
            updated_at=now(),
        )

    @staticmethod
    def _reasoning_entry(payload: ReasoningCreate) -> SimpleNamespace:
        return SimpleNamespace(
            id=str(uuid4()),
            message_id="",
            content=payload.content,
            summary=payload.summary,
            reasoning_metadata=payload.metadata,
            sequence=payload.sequence,
            created_at=now(),
            updated_at=now(),
        )


class FakeUserFileService:
    """Fake user file service for attachment URL hydration."""

    async def create_download_url(self, file_id: str):
        """Return a fresh deterministic attachment URL."""
        return (
            SimpleNamespace(
                id=file_id,
                content_type="image/png",
                original_filename="fresh.png",
            ),
            f"https://fresh.example.test/{file_id}.png",
        )


@pytest.fixture
def fake_service() -> FakeConversationService:
    """Return a fake conversation service."""
    return FakeConversationService()


def create_conversation_test_app(fake_service: FakeConversationService):
    """Create an app with conversation dependencies overridden."""
    app = create_app()
    app.dependency_overrides[get_conversation_service] = lambda: fake_service
    app.dependency_overrides[get_conversation_user_file_service] = lambda: FakeUserFileService()
    return app


@pytest.mark.asyncio
async def test_conversation_crud_routes(fake_service: FakeConversationService) -> None:
    """Conversation routes should support create, list, get, update, and delete."""
    app = create_conversation_test_app(fake_service)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/conversations",
            json={"user_id": "user-123", "title": "Planning"},
        )
        conversation_id = created.json()["id"]
        listed = await client.get("/conversations")
        fetched = await client.get(f"/conversations/{conversation_id}")
        updated = await client.patch(
            f"/conversations/{conversation_id}",
            json={"title": "Updated planning"},
        )
        deleted = await client.delete(f"/conversations/{conversation_id}")

    assert created.status_code == 201
    assert created.json()["user_id"] == "user-123"
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert fetched.status_code == 200
    assert fetched.json()["messages"] == []
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated planning"
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_conversation_list_filters_by_user_id(
    fake_service: FakeConversationService,
) -> None:
    """Conversation listing should support user scoping."""
    app = create_conversation_test_app(fake_service)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/conversations", json={"user_id": "user-123", "title": "Planning"})
        await client.post("/conversations", json={"user_id": "user-456", "title": "Other"})
        response = await client.get("/conversations", params={"user_id": "user-123"})

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["user_id"] == "user-123"


@pytest.mark.asyncio
async def test_message_can_contain_multiple_tool_calls_and_reasoning_entries(
    fake_service: FakeConversationService,
) -> None:
    """A single agent message should support multiple tool calls and reasoning entries."""
    app = create_conversation_test_app(fake_service)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        conversation = await client.post(
            "/conversations",
            json={"user_id": "user-123", "title": "Planning"},
        )
        conversation_id = conversation.json()["id"]
        created = await client.post(
            f"/conversations/{conversation_id}/messages",
            json={
                "role": "agent",
                "text": "I checked context and calendar before answering.",
                "tool_calls": [
                    {
                        "tool_call_id": "call_1",
                        "name": "get_demo_context",
                        "arguments": {"topic": "planning"},
                        "result": {"content": "planning context"},
                        "sequence": 0,
                    },
                    {
                        "tool_call_id": "call_2",
                        "name": "get_calendar",
                        "arguments": {"date": "2026-06-05"},
                        "status": "completed",
                        "sequence": 1,
                    },
                ],
                "reasoning_entries": [
                    {
                        "content": "Need planning context first.",
                        "summary": "context",
                        "sequence": 0,
                    },
                    {
                        "content": "Need calendar constraints next.",
                        "summary": "calendar",
                        "sequence": 1,
                    },
                ],
                "metadata": {"node": "model"},
            },
        )

    body = created.json()
    assert created.status_code == 201
    assert body["metadata"] == {"node": "model"}
    assert len(body["tool_calls"]) == 2
    assert body["tool_calls"][0]["name"] == "get_demo_context"
    assert body["tool_calls"][1]["name"] == "get_calendar"
    assert len(body["reasoning_entries"]) == 2
    assert body["reasoning_entries"][0]["summary"] == "context"


@pytest.mark.asyncio
async def test_message_can_persist_attachments(
    fake_service: FakeConversationService,
) -> None:
    """User messages can store attachments without requiring text."""
    app = create_conversation_test_app(fake_service)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        conversation = await client.post(
            "/conversations",
            json={"user_id": "user-123", "title": "Planning"},
        )
        conversation_id = conversation.json()["id"]
        created = await client.post(
            f"/conversations/{conversation_id}/messages",
            json={
                "role": "user",
                "attachments": [
                    {
                        "url": "https://files.example.test/avatar.png",
                        "mediaType": "image/png",
                        "title": "avatar.png",
                    }
                ],
            },
        )
        listed = await client.get(f"/conversations/{conversation_id}/messages")

    body = created.json()
    assert created.status_code == 201
    assert body["text"] is None
    assert body["attachments"] == [
        {
            "url": "https://files.example.test/avatar.png",
            "mediaType": "image/png",
            "title": "avatar.png",
        }
    ]
    assert body["metadata"]["attachments"] == body["attachments"]
    assert listed.json()[0]["attachments"] == body["attachments"]


@pytest.mark.asyncio
async def test_message_attachment_urls_are_refreshed_from_provider_file_id(
    fake_service: FakeConversationService,
) -> None:
    """Conversation responses should not replay stale stored presigned URLs."""
    app = create_conversation_test_app(fake_service)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        conversation = await client.post(
            "/conversations",
            json={"user_id": "user-123", "title": "Planning"},
        )
        conversation_id = conversation.json()["id"]
        created = await client.post(
            f"/conversations/{conversation_id}/messages",
            json={
                "role": "user",
                "attachments": [
                    {
                        "url": "https://expired.example.test/avatar.png",
                        "mediaType": "image/png",
                        "title": "avatar.png",
                        "providerFileId": "file-id",
                    }
                ],
            },
        )
        listed = await client.get(f"/conversations/{conversation_id}/messages")

    refreshed_attachment = {
        "url": "https://fresh.example.test/file-id.png",
        "mediaType": "image/png",
        "title": "fresh.png",
        "providerFileId": "file-id",
    }
    assert created.status_code == 201
    assert created.json()["attachments"] == [refreshed_attachment]
    assert listed.json()[0]["attachments"] == [refreshed_attachment]


@pytest.mark.asyncio
async def test_nested_tool_call_crud_routes(fake_service: FakeConversationService) -> None:
    """Tool call routes should support create, list, get, update, and delete."""
    app = create_conversation_test_app(fake_service)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        conversation = await client.post(
            "/conversations",
            json={"user_id": "user-123", "title": "Planning"},
        )
        conversation_id = conversation.json()["id"]
        message = await client.post(
            f"/conversations/{conversation_id}/messages",
            json={"role": "agent", "text": "Working on it."},
        )
        message_id = message.json()["id"]
        created = await client.post(
            f"/conversations/{conversation_id}/messages/{message_id}/tool-calls",
            json={"name": "get_demo_context", "arguments": {"topic": "planning"}},
        )
        tool_call_id = created.json()["id"]
        listed = await client.get(
            f"/conversations/{conversation_id}/messages/{message_id}/tool-calls"
        )
        fetched = await client.get(
            f"/conversations/{conversation_id}/messages/{message_id}/tool-calls/{tool_call_id}"
        )
        updated = await client.patch(
            f"/conversations/{conversation_id}/messages/{message_id}/tool-calls/{tool_call_id}",
            json={"status": "failed", "result": {"error": "timeout"}},
        )
        deleted = await client.delete(
            f"/conversations/{conversation_id}/messages/{message_id}/tool-calls/{tool_call_id}"
        )

    assert created.status_code == 201
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "get_demo_context"
    assert updated.status_code == 200
    assert updated.json()["status"] == "failed"
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_nested_reasoning_crud_routes(fake_service: FakeConversationService) -> None:
    """Reasoning routes should support create, list, get, update, and delete."""
    app = create_conversation_test_app(fake_service)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        conversation = await client.post(
            "/conversations",
            json={"user_id": "user-123", "title": "Planning"},
        )
        conversation_id = conversation.json()["id"]
        message = await client.post(
            f"/conversations/{conversation_id}/messages",
            json={"role": "agent", "text": "Working on it."},
        )
        message_id = message.json()["id"]
        created = await client.post(
            f"/conversations/{conversation_id}/messages/{message_id}/reasoning",
            json={"content": "Need to inspect goals.", "summary": "goals"},
        )
        reasoning_id = created.json()["id"]
        listed = await client.get(
            f"/conversations/{conversation_id}/messages/{message_id}/reasoning"
        )
        fetched = await client.get(
            f"/conversations/{conversation_id}/messages/{message_id}/reasoning/{reasoning_id}"
        )
        updated = await client.patch(
            f"/conversations/{conversation_id}/messages/{message_id}/reasoning/{reasoning_id}",
            json={"summary": "updated goals"},
        )
        deleted = await client.delete(
            f"/conversations/{conversation_id}/messages/{message_id}/reasoning/{reasoning_id}"
        )

    assert created.status_code == 201
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert fetched.status_code == 200
    assert fetched.json()["content"] == "Need to inspect goals."
    assert updated.status_code == 200
    assert updated.json()["summary"] == "updated goals"
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_conversation_not_found_uses_standard_error(
    fake_service: FakeConversationService,
) -> None:
    """Missing conversations should return the standard error shape."""
    app = create_conversation_test_app(fake_service)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/conversations/missing")

    assert response.status_code == 404
    assert response.json() == {
        "status": 404,
        "message": "conversation not found",
        "error_tag": "conversation_not_found",
    }


@pytest.mark.asyncio
async def test_message_requires_content(fake_service: FakeConversationService) -> None:
    """Messages should require text, tool calls, or reasoning entries."""
    app = create_conversation_test_app(fake_service)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        conversation = await client.post(
            "/conversations",
            json={"user_id": "user-123", "title": "Planning"},
        )
        conversation_id = conversation.json()["id"]
        response = await client.post(
            f"/conversations/{conversation_id}/messages",
            json={"role": "user"},
        )

    assert response.status_code == 422
    assert response.json()["error_tag"] == "request_validation_error"
