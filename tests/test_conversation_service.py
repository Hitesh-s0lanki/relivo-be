# tests/test_conversation_service.py
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.schema.conversation import (
    ConversationCreate,
    ConversationList,
    ConversationSchema,
    ConversationStatus,
    ConversationUpdate,
    GetAllConversationsRequest,
)


def _make_mock_conv(
    conv_id: uuid.UUID | None = None,
    user_id: str = "u1",
    title: str | None = "T",
    status: int = 1,
) -> MagicMock:
    conv = MagicMock()
    conv.id = conv_id or uuid.uuid4()
    conv.user_id = user_id
    conv.title = title
    conv.status = status
    conv.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    conv.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return conv


def _make_mock_session(scalar_result=None, all_result=None):
    """Return a mock async_session context manager."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.flush = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = scalar_result
    if all_result is not None:
        mock_result.scalars.return_value.all.return_value = all_result
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def mock_refresh(obj):
        pass

    mock_session.refresh = mock_refresh
    return mock_session


@pytest.mark.asyncio
async def test_create_conversation_returns_schema():
    from src.services.conversation_service import ConversationService

    mock_conv = _make_mock_conv()
    mock_session = _make_mock_session(scalar_result=mock_conv)

    with patch("src.services.conversation_service.async_session", return_value=mock_session):
        service = ConversationService()
        result = await service.create_conversation(
            ConversationCreate(userId="u1", title="Test")
        )

    assert isinstance(result, ConversationSchema)
    assert result.user_id == mock_conv.user_id


@pytest.mark.asyncio
async def test_get_all_conversations_returns_list():
    from src.services.conversation_service import ConversationService

    convs = [_make_mock_conv(), _make_mock_conv()]
    mock_session = _make_mock_session(all_result=convs)

    with patch("src.services.conversation_service.async_session", return_value=mock_session):
        service = ConversationService()
        result = await service.get_all_conversations(GetAllConversationsRequest(userId="u1"))

    assert isinstance(result, ConversationList)
    assert len(result.conversations) == 2


@pytest.mark.asyncio
async def test_get_all_conversations_missing_user_id_raises_400():
    from fastapi import HTTPException
    from src.services.conversation_service import ConversationService

    service = ConversationService()
    with pytest.raises(HTTPException) as exc_info:
        await service.get_all_conversations(GetAllConversationsRequest(userId=""))
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_get_conversation_not_found_raises_404():
    from fastapi import HTTPException
    from src.services.conversation_service import ConversationService

    mock_session = _make_mock_session(scalar_result=None)

    with patch("src.services.conversation_service.async_session", return_value=mock_session):
        service = ConversationService()
        with pytest.raises(HTTPException) as exc_info:
            await service.get_conversation(str(uuid.uuid4()), "u1")
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_conversation_status_returns_deleted_when_missing():
    from src.services.conversation_service import ConversationService

    mock_session = _make_mock_session(scalar_result=None)

    with patch("src.services.conversation_service.async_session", return_value=mock_session):
        service = ConversationService()
        result = await service.get_conversation_status(str(uuid.uuid4()))

    assert result == int(ConversationStatus.DELETED)


@pytest.mark.asyncio
async def test_get_messages_missing_conversation_id_raises_400():
    from fastapi import HTTPException
    from src.schema.chat import ConversationMessagesRequest
    from src.services.conversation_service import ConversationService

    service = ConversationService()
    with pytest.raises(HTTPException) as exc_info:
        await service.get_messages(ConversationMessagesRequest())
    assert exc_info.value.status_code == 400
