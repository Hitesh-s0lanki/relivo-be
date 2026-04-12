import json
from src.utils.data_protocol import SSEEvent, StreamProtocolBuilder


def test_sse_event_dict_to_sse():
    event = SSEEvent({"type": "text-delta", "id": "t1", "delta": "hi"})
    result = event.to_sse()
    assert result == 'data: {"type": "text-delta", "id": "t1", "delta": "hi"}\n\n'


def test_sse_event_string_to_sse():
    event = SSEEvent("[DONE]")
    assert event.to_sse() == "data: [DONE]\n\n"


def test_message_start():
    sse = StreamProtocolBuilder.message_start("msg_1").to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "start", "messageId": "msg_1"}


def test_stream_text_start():
    sse = StreamProtocolBuilder.stream_text_start("t1").to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "text-start", "id": "t1"}


def test_stream_text_delta():
    sse = StreamProtocolBuilder.stream_text_delta("t1", "hello").to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "text-delta", "id": "t1", "delta": "hello"}


def test_stream_text_end():
    sse = StreamProtocolBuilder.stream_text_end("t1").to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "text-end", "id": "t1"}


def test_tool_input_start():
    sse = StreamProtocolBuilder.tool_input_start("call_1", "search").to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "tool-input-start", "toolCallId": "call_1", "toolName": "search"}


def test_tool_input_available():
    sse = StreamProtocolBuilder.tool_input_available("call_1", "search", {"q": "test"}).to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {
        "type": "tool-input-available",
        "toolCallId": "call_1",
        "toolName": "search",
        "input": {"q": "test"},
    }


def test_tool_output_available():
    sse = StreamProtocolBuilder.tool_output_available("call_1", {"result": "found"}).to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {
        "type": "tool-output-available",
        "toolCallId": "call_1",
        "output": {"result": "found"},
    }


def test_message_end():
    sse = StreamProtocolBuilder.message_end({"usage": 100}).to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "finish", "messageMetadata": {"usage": 100}}


def test_terminate_stream():
    sse = StreamProtocolBuilder.terminate_stream().to_sse()
    assert sse == "data: [DONE]\n\n"


def test_error_part():
    sse = StreamProtocolBuilder.error_part("something broke", "internal_error").to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "error", "errorText": "internal_error:something broke"}


def test_data_heartbeat():
    sse = StreamProtocolBuilder.data_custom("heartbeat", {"ts": 123}).to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "data-heartbeat", "data": {"ts": 123}}
