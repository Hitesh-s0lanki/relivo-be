# tests/test_schemas.py
from src.schema.conversation import ConversationCreate, ConversationStatus, ConversationSchema
from src.schema.chat import UserMessageRequest, CancelMessageRequest, ConversationMessagesResponse


def test_conversation_create_accepts_camelcase():
    req = ConversationCreate.model_validate({"userId": "u1", "title": "T"})
    assert req.user_id == "u1"


def test_conversation_schema_serializes_camelcase():
    schema = ConversationSchema(
        id="abc",
        userId="u1",
        title="T",
        status=ConversationStatus.ACTIVE,
        createdAt="2026-01-01T00:00:00+00:00",
        updatedAt="2026-01-01T00:00:00+00:00",
    )
    data = schema.model_dump(by_alias=True)
    assert "userId" in data
    assert "createdAt" in data


def test_user_message_request_accepts_camelcase():
    req = UserMessageRequest.model_validate({
        "conversationId": "conv1",
        "userId": "u1",
        "userMessage": "hello",
        "userMessageTimestamp": 0,
        "attachments": [],
    })
    assert req.conversation_id == "conv1"
    assert req.user_message == "hello"


def test_user_message_request_defaults():
    req = UserMessageRequest()
    assert req.conversation_id == ""
    assert req.attachments == []


def test_cancel_message_request_accepts_camelcase():
    req = CancelMessageRequest.model_validate({
        "responseId": "r1",
        "userMessageRequest": {
            "conversationId": "c1",
            "userId": "u1",
            "userMessage": "hi",
        }
    })
    assert req.response_id == "r1"
    assert req.user_message_request.conversation_id == "c1"


def test_conversation_messages_response_serializes_camelcase():
    resp = ConversationMessagesResponse()
    data = resp.model_dump(by_alias=True)
    assert "hasMore" in data
    assert "nextOffset" in data
