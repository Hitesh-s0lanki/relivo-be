# tests/test_chat_route.py
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.schema.chat import UserMessageRequest, CancelMessageRequest


# ── Schema tests ──────────────────────────────────────────────────────────────

def test_user_message_request_requires_conversation_id_and_message():
    req = UserMessageRequest(
        conversationId="c1", userId="u1", userMessage="hello"
    )
    assert req.conversation_id == "c1"
    assert req.user_message == "hello"


def test_user_message_request_empty_defaults():
    req = UserMessageRequest()
    assert req.conversation_id == ""
    assert req.user_message == ""


# ── Service streaming test ────────────────────────────────────────────────────

async def fake_iter_events(messages):
    yield {"type": "message_start", "message_id": "msg1"}
    yield {"type": "text_start", "text_id": "t1"}
    yield {"type": "text_delta", "text_id": "t1", "content": "Hi"}
    yield {"type": "text_delta", "text_id": "t1", "content": " there!"}
    yield {"type": "text_end", "text_id": "t1"}
    yield {"type": "message_end", "metadata": {}}


@pytest.mark.asyncio
async def test_chat_service_stream_yields_sse_and_done():
    from src.services.chat_service import ChatService

    conv_id = uuid.uuid4()
    request = UserMessageRequest(
        conversationId=str(conv_id), userId="u1", userMessage="hello"
    )

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_conv = MagicMock()
    mock_conv.id = conv_id

    execute_count = 0

    async def mock_execute(stmt, *args, **kwargs):
        nonlocal execute_count
        execute_count += 1
        result = MagicMock()
        if execute_count == 1:
            # _validate_conversation
            result.scalar_one_or_none.return_value = mock_conv
        elif execute_count == 2:
            # _load_history
            result.scalars.return_value.all.return_value = []
        else:
            result.rowcount = 1
        return result

    mock_session.execute = mock_execute

    async def mock_refresh(obj):
        pass

    mock_session.refresh = mock_refresh

    mock_agent = MagicMock()
    mock_agent.iter_events = fake_iter_events

    chunks = []

    with (
        patch("src.services.chat_service.async_session", return_value=mock_session),
        patch("src.services.chat_service.EchoAgent", return_value=mock_agent),
        patch("src.services.chat_service.ConversationService") as MockConvSvc,
        patch("src.services.chat_service.stream_registry") as mock_registry,
    ):
        MockConvSvc.return_value.update_conversation_status = AsyncMock()
        mock_registry.register = AsyncMock()
        mock_registry.is_cancelled = MagicMock(return_value=False)
        mock_registry.publish = AsyncMock()
        mock_registry.mark_done = AsyncMock()
        mock_registry.unregister = AsyncMock()
        service = ChatService(request)
        async for chunk in service.stream():
            chunks.append(chunk)

    assert chunks[-1] == "data: [DONE]\n\n"
    text_deltas = [
        json.loads(c.removeprefix("data: ").strip())
        for c in chunks
        if '"text-delta"' in c
    ]
    assert [td["delta"] for td in text_deltas] == ["Hi", " there!"]


# ── Route tests ───────────────────────────────────────────────────────────────

async def minimal_stream():
    yield 'data: {"type": "start", "messageId": "m1"}\n\n'
    yield 'data: {"type": "text-start", "id": "t1"}\n\n'
    yield 'data: {"type": "text-delta", "id": "t1", "delta": "hi"}\n\n'
    yield 'data: {"type": "text-end", "id": "t1"}\n\n'
    yield 'data: {"type": "finish", "messageMetadata": {}}\n\n'
    yield "data: [DONE]\n\n"


def test_chat_endpoint_streams_sse():
    from fastapi.testclient import TestClient
    from src.main import app

    mock_service = MagicMock()
    mock_service.stream = minimal_stream

    with (
        patch("src.routes.chat.ChatService", return_value=mock_service),
        patch("src.routes.chat.add_heartbeat_to_stream", side_effect=lambda g, **kw: g),
    ):
        client = TestClient(app)
        response = client.post(
            "/chat",
            json={
                "conversationId": str(uuid.uuid4()),
                "userId": "u1",
                "userMessage": "hello",
            },
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "text-delta" in response.text
    assert "[DONE]" in response.text


def test_chat_endpoint_accepts_camelcase_body():
    from fastapi.testclient import TestClient
    from src.main import app

    mock_service = MagicMock()
    mock_service.stream = minimal_stream

    with (
        patch("src.routes.chat.ChatService", return_value=mock_service),
        patch("src.routes.chat.add_heartbeat_to_stream", side_effect=lambda g, **kw: g),
    ):
        client = TestClient(app)
        # All keys in camelCase (as the FE sends them)
        response = client.post(
            "/chat",
            json={
                "conversationId": str(uuid.uuid4()),
                "userId": "u1",
                "userMessage": "test message",
                "userMessageTimestamp": 1234567890,
                "attachments": [],
            },
        )

    assert response.status_code == 200


def test_cancel_response_with_active_stream():
    from fastapi.testclient import TestClient
    from src.main import app
    from src.utils.stream_registry import stream_registry

    cid = str(uuid.uuid4())

    with patch.object(stream_registry, "cancel", new=AsyncMock(return_value=True)):
        client = TestClient(app)
        response = client.post(
            "/conversation/cancel-response",
            json={
                "responseId": "r1",
                "userMessageRequest": {
                    "conversationId": cid,
                    "userId": "u1",
                    "userMessage": "hi",
                },
            },
        )

    assert response.status_code == 200
    assert "cancel" in response.json()["detail"].lower()


def test_cancel_response_no_active_stream():
    from fastapi.testclient import TestClient
    from src.main import app
    from src.utils.stream_registry import stream_registry

    cid = str(uuid.uuid4())

    with patch.object(stream_registry, "cancel", new=AsyncMock(return_value=False)):
        client = TestClient(app)
        response = client.post(
            "/conversation/cancel-response",
            json={
                "responseId": "r1",
                "userMessageRequest": {"conversationId": cid, "userId": "u1", "userMessage": "hi"},
            },
        )

    assert response.status_code == 200
    assert "no active stream" in response.json()["detail"].lower()


def test_resume_stream_not_streaming_returns_finalized():
    from fastapi.testclient import TestClient
    from src.main import app
    from src.schema.conversation import ConversationStatus

    cid = str(uuid.uuid4())

    with patch("src.routes.chat.ConversationService") as MockSvc:
        MockSvc.return_value.get_conversation_status = AsyncMock(
            return_value=int(ConversationStatus.ACTIVE)
        )
        client = TestClient(app)
        response = client.get(f"/chat/resume-stream/{cid}")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "already_finalized" in response.text
