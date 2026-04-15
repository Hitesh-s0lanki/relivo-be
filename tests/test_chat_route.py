import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.schema.chat import UserMessageRequest


def test_user_message_request_requires_no_fields():
    req = UserMessageRequest(userId="u1", userMessage="hello")
    assert req.conversation_id == ""


def test_user_message_request_empty_message_allowed():
    req = UserMessageRequest(userId="u1", userMessage="")
    assert req.user_message == ""


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

    request = UserMessageRequest(userId="u1", userMessage="hello")

    # Mock the DB session
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    # _get_or_create_conversation: no conversation_id → INSERT new conversation
    # The conversation needs an .id attribute
    mock_conv = MagicMock()
    mock_conv.id = uuid.uuid4()

    # _load_history: returns empty list
    mock_history_result = MagicMock()
    mock_history_result.scalars.return_value.all.return_value = []

    # _get_or_create_conversation does db.add + db.flush → conv.id is set
    # We simulate this by patching the session's add to set conv.id when Conversation is added
    added_objects = []
    def capture_add(obj):
        added_objects.append(obj)
    mock_session.add = MagicMock(side_effect=capture_add)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    # execute() returns different things depending on what's being queried
    execute_call_count = 0
    async def mock_execute(stmt, *args, **kwargs):
        nonlocal execute_call_count
        execute_call_count += 1
        result = MagicMock()
        if execute_call_count == 1:
            # _load_history query
            result.scalars.return_value.all.return_value = []
        else:
            # _finalize UPDATE query
            result.rowcount = 1
        return result
    mock_session.execute = mock_execute

    mock_agent = MagicMock()
    mock_agent.iter_events = fake_iter_events

    chunks = []
    with patch("src.services.chat_service.async_session", return_value=mock_session), \
         patch("src.services.chat_service.EchoAgent", return_value=mock_agent):

        service = ChatService(request)
        async for chunk in service.stream():
            chunks.append(chunk)

    assert chunks[-1] == "data: [DONE]\n\n"
    text_deltas = [
        json.loads(c.removeprefix("data: ").strip())
        for c in chunks if '"text-delta"' in c
    ]
    assert [td["delta"] for td in text_deltas] == ["Hi", " there!"]


async def minimal_stream():
    yield 'data: {"type": "start", "messageId": "m1"}\n\n'
    yield 'data: {"type": "text-start", "id": "t1"}\n\n'
    yield 'data: {"type": "text-delta", "id": "t1", "delta": "hi"}\n\n'
    yield 'data: {"type": "text-end", "id": "t1"}\n\n'
    yield 'data: {"type": "finish", "messageMetadata": {}}\n\n'
    yield "data: [DONE]\n\n"


def test_chat_endpoint_streams_sse():
    from src.main import app
    from fastapi.testclient import TestClient

    mock_service = MagicMock()
    mock_service.stream = minimal_stream

    with patch("src.routes.chat.ChatService", return_value=mock_service), \
         patch("src.routes.chat.add_heartbeat_to_stream", side_effect=lambda g, **kw: g):

        client = TestClient(app)
        response = client.post(
            "/chat",
            json={"userId": "u1", "userMessage": "hello"},
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    body = response.text
    assert "text-delta" in body
    assert "[DONE]" in body


def test_chat_endpoint_accepts_empty_body():
    from src.main import app
    from fastapi.testclient import TestClient

    mock_service = MagicMock()
    mock_service.stream = minimal_stream

    with patch("src.routes.chat.ChatService", return_value=mock_service), \
         patch("src.routes.chat.add_heartbeat_to_stream", side_effect=lambda g, **kw: g):

        client = TestClient(app)
        response = client.post("/chat", json={})

    assert response.status_code == 200
