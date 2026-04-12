import uuid
from collections.abc import AsyncGenerator

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from src.app_config import settings
from src.utils.data_protocol import StreamProtocolBuilder


class BaseAgent:
    """
    Base agent wrapping a LangGraph create_react_agent graph.

    Exposes:
    - iter_events(messages) → AsyncGenerator of structured internal event dicts
    - stream(messages)      → AsyncGenerator of SSE strings (Vercel AI SDK format)
    - event_to_sse(event)   → str | None — static converter for use by ChatService
    """

    def __init__(self, model: str, system_prompt: str, tools: list):
        self.system_prompt = system_prompt
        self.llm = ChatOpenAI(
            model=model,
            api_key=settings.openai_api_key,
        )
        self.graph = create_react_agent(self.llm, tools)

    async def iter_events(self, messages: list) -> AsyncGenerator[dict, None]:
        """
        Iterate over structured internal events produced by the LangGraph agent.

        Event types:
          message_start  — {"type": "message_start", "message_id": str}
          text_start     — {"type": "text_start", "text_id": str}
          text_delta     — {"type": "text_delta", "text_id": str, "content": str}
          text_end       — {"type": "text_end", "text_id": str}
          tool_start     — {"type": "tool_start", "tool_call_id": str, "tool_name": str, "tool_input": dict}
          tool_end       — {"type": "tool_end", "tool_call_id": str, "tool_output": dict}
          message_end    — {"type": "message_end", "metadata": dict}
        """
        message_id = str(uuid.uuid4())[:8]
        yield {"type": "message_start", "message_id": message_id}

        # Prepend system message so the agent always gets the persona
        all_messages = [SystemMessage(content=self.system_prompt)] + list(messages)

        text_id: str | None = None
        emitting_text = False

        try:
            async for event in self.graph.astream_events({"messages": all_messages}, version="v2"):
                event_type: str = event["event"]
                node: str = event.get("metadata", {}).get("langgraph_node", "")

                if event_type == "on_chat_model_stream" and node == "agent":
                    chunk = event["data"]["chunk"]
                    content = chunk.content if isinstance(chunk.content, str) else ""
                    if content:
                        if not emitting_text:
                            text_id = event["run_id"][:8]
                            emitting_text = True
                            yield {"type": "text_start", "text_id": text_id}
                        yield {"type": "text_delta", "text_id": text_id, "content": content}

                elif event_type == "on_chat_model_end" and node == "agent" and emitting_text:
                    assert text_id is not None  # invariant: emitting_text is True only when text_id was assigned
                    yield {"type": "text_end", "text_id": text_id}
                    emitting_text = False
                    text_id = None

                elif event_type == "on_tool_start":
                    tool_call_id = event["run_id"][:8]
                    tool_name = event["name"]
                    tool_input = event["data"].get("input") or {}
                    yield {
                        "type": "tool_start",
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                    }

                elif event_type == "on_tool_end":
                    tool_call_id = event["run_id"][:8]
                    raw_output = event["data"].get("output", "")
                    tool_output = (
                        raw_output if isinstance(raw_output, dict) else {"output": str(raw_output)}
                    )
                    yield {
                        "type": "tool_end",
                        "tool_call_id": tool_call_id,
                        "tool_output": tool_output,
                    }
        finally:
            yield {"type": "message_end", "metadata": {}}

    async def stream(self, messages: list) -> AsyncGenerator[str, None]:
        """Convert iter_events output to SSE strings."""
        async for ev in self.iter_events(messages):
            sse = self.event_to_sse(ev)
            if sse is not None:
                yield sse
        yield StreamProtocolBuilder.terminate_stream().to_sse()

    @staticmethod
    def event_to_sse(event: dict) -> str | None:
        """Map an internal structured event to an SSE string. Returns None for unknown types."""
        t = event["type"]
        if t == "message_start":
            return StreamProtocolBuilder.message_start(event["message_id"]).to_sse()
        if t == "text_start":
            return StreamProtocolBuilder.stream_text_start(event["text_id"]).to_sse()
        if t == "text_delta":
            return StreamProtocolBuilder.stream_text_delta(event["text_id"], event["content"]).to_sse()
        if t == "text_end":
            return StreamProtocolBuilder.stream_text_end(event["text_id"]).to_sse()
        if t == "tool_start":
            return (
                StreamProtocolBuilder.tool_input_start(event["tool_call_id"], event["tool_name"]).to_sse()
                + StreamProtocolBuilder.tool_input_available(
                    event["tool_call_id"], event["tool_name"], event["tool_input"]
                ).to_sse()
            )
        if t == "tool_end":
            return StreamProtocolBuilder.tool_output_available(
                event["tool_call_id"], event["tool_output"]
            ).to_sse()
        if t == "message_end":
            return StreamProtocolBuilder.message_end(event.get("metadata", {})).to_sse()
        return None
