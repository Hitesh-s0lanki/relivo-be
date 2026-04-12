import uuid
from src.db.models import Conversation, Message, ToolCall


def test_conversation_defaults():
    conv = Conversation(user_id="u1")
    assert conv.user_id == "u1"
    assert isinstance(conv.id, uuid.UUID)
    assert conv.metadata_ == {}


def test_message_defaults():
    msg = Message(
        conversation_id=uuid.uuid4(),
        role="user",
        content="hello",
        sequence_number=1,
    )
    assert msg.status == "completed"
    assert isinstance(msg.id, uuid.UUID)


def test_tool_call_fields():
    tc = ToolCall(
        message_id=uuid.uuid4(),
        tool_call_id="run_abc",
        tool_name="search",
        tool_input={"query": "test"},
        tool_output={"result": "found"},
    )
    assert tc.tool_name == "search"
    assert isinstance(tc.id, uuid.UUID)
