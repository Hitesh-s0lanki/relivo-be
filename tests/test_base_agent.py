import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage


def make_stream_event(event_type, node="agent", run_id="run_abc123", **data):
    return {
        "event": event_type,
        "name": "ChatOpenAI",
        "run_id": run_id,
        "metadata": {"langgraph_node": node},
        "data": data,
    }


def text_chunk(content):
    chunk = MagicMock()
    chunk.content = content
    return chunk


async def fake_astream_events(input_dict, **kwargs):
    yield make_stream_event("on_chat_model_stream", chunk=text_chunk("Hello"))
    yield make_stream_event("on_chat_model_stream", chunk=text_chunk(" world"))
    yield make_stream_event("on_chat_model_end")


@pytest.mark.asyncio
async def test_iter_events_text_only():
    from src.agents.base_agent import BaseAgent

    with patch("src.agents.base_agent.ChatOpenAI"), \
         patch("src.agents.base_agent.create_react_agent") as mock_create:

        mock_graph = MagicMock()
        mock_graph.astream_events = fake_astream_events
        mock_create.return_value = mock_graph

        agent = BaseAgent(model="gpt-4o-mini", system_prompt="You are helpful.", tools=[])
        events = []
        async for ev in agent.iter_events([HumanMessage(content="hi")]):
            events.append(ev)

    types = [e["type"] for e in events]
    assert "message_start" in types
    assert "text_start" in types
    assert types.count("text_delta") == 2
    assert "text_end" in types
    assert "message_end" in types

    deltas = [e["content"] for e in events if e["type"] == "text_delta"]
    assert deltas == ["Hello", " world"]


@pytest.mark.asyncio
async def test_iter_events_tool_call():
    from src.agents.base_agent import BaseAgent

    async def with_tool_events(input_dict, **kwargs):
        yield make_stream_event("on_tool_start", node="tools", run_id="tool_run_1",
                                input={"query": "weather"})
        yield make_stream_event("on_tool_end", node="tools", run_id="tool_run_1",
                                output="Sunny, 25°C")
        yield make_stream_event("on_chat_model_stream", chunk=text_chunk("It is sunny."))
        yield make_stream_event("on_chat_model_end")

    with patch("src.agents.base_agent.ChatOpenAI"), \
         patch("src.agents.base_agent.create_react_agent") as mock_create:

        mock_graph = MagicMock()
        mock_graph.astream_events = with_tool_events
        mock_create.return_value = mock_graph

        agent = BaseAgent(model="gpt-4o-mini", system_prompt="You are helpful.", tools=[])
        events = []
        async for ev in agent.iter_events([HumanMessage(content="weather?")]):
            events.append(ev)

    types = [e["type"] for e in events]
    assert "tool_start" in types
    assert "tool_end" in types

    tool_start = next(e for e in events if e["type"] == "tool_start")
    assert tool_start["tool_name"] == "ChatOpenAI"
    assert tool_start["tool_input"] == {"query": "weather"}

    tool_end = next(e for e in events if e["type"] == "tool_end")
    assert tool_end["tool_output"] == {"output": "Sunny, 25°C"}


@pytest.mark.asyncio
async def test_stream_yields_sse_strings():
    from src.agents.base_agent import BaseAgent

    with patch("src.agents.base_agent.ChatOpenAI"), \
         patch("src.agents.base_agent.create_react_agent") as mock_create:

        mock_graph = MagicMock()
        mock_graph.astream_events = fake_astream_events
        mock_create.return_value = mock_graph

        agent = BaseAgent(model="gpt-4o-mini", system_prompt="You are helpful.", tools=[])
        chunks = []
        async for chunk in agent.stream([HumanMessage(content="hi")]):
            chunks.append(chunk)

    assert all(c.startswith("data: ") for c in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"

    text_deltas = [
        json.loads(c.removeprefix("data: ").strip())
        for c in chunks
        if '"text-delta"' in c
    ]
    assert [td["delta"] for td in text_deltas] == ["Hello", " world"]


def test_event_to_sse_text_delta():
    from src.agents.base_agent import BaseAgent

    sse = BaseAgent.event_to_sse({"type": "text_delta", "text_id": "t1", "content": "hi"})
    assert sse is not None
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "text-delta", "id": "t1", "delta": "hi"}


def test_event_to_sse_unknown_returns_none():
    from src.agents.base_agent import BaseAgent

    assert BaseAgent.event_to_sse({"type": "unknown_event"}) is None
