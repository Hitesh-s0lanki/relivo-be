# tests/test_conversation_route.py
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.schema.conversation import ConversationList, ConversationSchema, ConversationStatus
from src.schema.chat import ConversationMessagesResponse


def _schema(conv_id: str = None) -> ConversationSchema:
    return ConversationSchema(
        id=conv_id or str(uuid.uuid4()),
        userId="u1",
        title="Test",
        status=ConversationStatus.ACTIVE,
        createdAt="2026-01-01T00:00:00+00:00",
        updatedAt="2026-01-01T00:00:00+00:00",
    )


def test_create_conversation_returns_200():
    from fastapi.testclient import TestClient
    from src.main import app

    with patch("src.routes.conversation.ConversationService") as MockSvc:
        MockSvc.return_value.create_conversation = AsyncMock(return_value=_schema())
        client = TestClient(app)
        resp = client.post("/conversation/create", json={"userId": "u1", "title": "T"})

    assert resp.status_code == 200
    assert resp.json()["userId"] == "u1"


def test_get_all_conversations_returns_list():
    from fastapi.testclient import TestClient
    from src.main import app

    with patch("src.routes.conversation.ConversationService") as MockSvc:
        MockSvc.return_value.get_all_conversations = AsyncMock(
            return_value=ConversationList(conversations=[_schema(), _schema()])
        )
        client = TestClient(app)
        resp = client.post("/conversation/get-all", json={"userId": "u1"})

    assert resp.status_code == 200
    assert len(resp.json()["conversations"]) == 2


def test_get_conversation_returns_schema():
    from fastapi.testclient import TestClient
    from src.main import app

    cid = str(uuid.uuid4())
    with patch("src.routes.conversation.ConversationService") as MockSvc:
        MockSvc.return_value.get_conversation = AsyncMock(return_value=_schema(cid))
        client = TestClient(app)
        resp = client.get(f"/conversation/get/{cid}?user_id=u1")

    assert resp.status_code == 200
    assert resp.json()["id"] == cid


def test_delete_conversation_returns_200():
    from fastapi.testclient import TestClient
    from src.main import app

    cid = str(uuid.uuid4())
    with patch("src.routes.conversation.ConversationService") as MockSvc:
        MockSvc.return_value.delete_conversation = AsyncMock(return_value=None)
        client = TestClient(app)
        resp = client.delete(f"/conversation/delete/{cid}?user_id=u1")

    assert resp.status_code == 200
    assert "deleted" in resp.json()["detail"].lower()


def test_get_conversation_messages_returns_response():
    from fastapi.testclient import TestClient
    from src.main import app

    cid = str(uuid.uuid4())
    with patch("src.routes.conversation.ConversationService") as MockSvc:
        MockSvc.return_value.get_messages = AsyncMock(
            return_value=ConversationMessagesResponse(
                messages=[], hasMore=False, nextOffset=0, count=0
            )
        )
        client = TestClient(app)
        resp = client.post(
            "/conversation/messages",
            json={"conversationId": cid, "userId": "u1"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert "hasMore" in data


def test_update_conversation_returns_schema():
    from fastapi.testclient import TestClient
    from src.main import app

    cid = str(uuid.uuid4())
    with patch("src.routes.conversation.ConversationService") as MockSvc:
        MockSvc.return_value.update_conversation = AsyncMock(return_value=_schema(cid))
        client = TestClient(app)
        resp = client.put(
            "/conversation/update",
            json={"id": cid, "userId": "u1", "title": "Updated"},
        )

    assert resp.status_code == 200
    assert resp.json()["id"] == cid
