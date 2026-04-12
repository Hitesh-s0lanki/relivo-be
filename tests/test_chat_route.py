import pytest
from pydantic import ValidationError
from src.schema.chat import ChatRequest


def test_chat_request_requires_user_id_and_message():
    req = ChatRequest(user_id="u1", message="hello")
    assert req.conversation_id is None


def test_chat_request_empty_message_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(user_id="u1", message="")
