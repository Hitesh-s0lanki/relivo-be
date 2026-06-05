"""Base LangChain agent harness with streaming helpers."""

from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver

AgentModel = str | BaseChatModel
AgentTool = BaseTool | Callable[..., Any] | dict[str, Any]
StreamMode = str | Sequence[str]


@dataclass(frozen=True, slots=True)
class BaseAgentConfig:
    """Configuration for the base LangChain agent harness."""

    model: AgentModel
    system_prompt: str = "You are a helpful assistant. Be concise, accurate, and direct."
    name: str = "base_agent"


class BaseAgent:
    """Small wrapper around LangChain's create_agent graph."""

    def __init__(
        self,
        config: BaseAgentConfig,
        *,
        tools: Sequence[AgentTool] | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        """Build the reusable LangChain agent graph."""
        self.config = config
        self.tools = list(tools or [])
        self.checkpointer = checkpointer or InMemorySaver()
        self.graph = create_agent(
            model=config.model,
            tools=self.tools,
            system_prompt=config.system_prompt,
            checkpointer=self.checkpointer,
            name=config.name,
        )

    def invoke(self, prompt: str, *, thread_id: str = "default", context: Any | None = None) -> str:
        """Run one agent turn and return the final assistant text."""
        kwargs = self._run_kwargs(thread_id=thread_id, context=context)
        result = self.graph.invoke(self._messages_input(prompt), **kwargs)
        return self._latest_text(result["messages"])

    async def ainvoke(
        self,
        prompt: str,
        *,
        thread_id: str = "default",
        context: Any | None = None,
    ) -> str:
        """Run one async agent turn and return the final assistant text."""
        kwargs = self._run_kwargs(thread_id=thread_id, context=context)
        result = await self.graph.ainvoke(self._messages_input(prompt), **kwargs)
        return self._latest_text(result["messages"])

    def stream_text(
        self,
        prompt: str,
        *,
        thread_id: str = "default",
        context: Any | None = None,
    ) -> Iterator[str]:
        """Yield assistant text chunks from a synchronous agent stream."""
        kwargs = self._run_kwargs(thread_id=thread_id, context=context)
        for chunk in self.graph.stream(
            self._messages_input(prompt),
            stream_mode="messages",
            version="v2",
            **kwargs,
        ):
            text = self._stream_chunk_text(chunk)
            if text:
                yield text

    def stream_events(
        self,
        prompt: str,
        *,
        thread_id: str = "default",
        context: Any | None = None,
        stream_mode: StreamMode = ("updates", "messages"),
    ) -> Iterator[Any]:
        """Yield the raw LangChain agent stream, including model/tool updates."""
        kwargs = self._run_kwargs(thread_id=thread_id, context=context)
        yield from self.graph.stream(
            self._messages_input(prompt),
            stream_mode=stream_mode,
            version="v2",
            **kwargs,
        )

    async def astream_text(
        self,
        prompt: str,
        *,
        thread_id: str = "default",
        context: Any | None = None,
    ) -> AsyncIterator[str]:
        """Yield assistant text chunks from an async agent stream."""
        kwargs = self._run_kwargs(thread_id=thread_id, context=context)
        async for chunk in self.graph.astream(
            self._messages_input(prompt),
            stream_mode="messages",
            version="v2",
            **kwargs,
        ):
            text = self._stream_chunk_text(chunk)
            if text:
                yield text

    async def astream_events(
        self,
        prompt: str,
        *,
        thread_id: str = "default",
        context: Any | None = None,
        stream_mode: StreamMode = ("updates", "messages"),
    ) -> AsyncIterator[Any]:
        """Yield the raw async LangChain agent stream, including model/tool updates."""
        kwargs = self._run_kwargs(thread_id=thread_id, context=context)
        async for chunk in self.graph.astream(
            self._messages_input(prompt),
            stream_mode=stream_mode,
            version="v2",
            **kwargs,
        ):
            yield chunk

    @staticmethod
    def _messages_input(prompt: str) -> dict[str, list[dict[str, str]]]:
        return {"messages": [{"role": "user", "content": prompt}]}

    @staticmethod
    def _run_kwargs(thread_id: str, context: Any | None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"config": {"configurable": {"thread_id": thread_id}}}
        if context is not None:
            kwargs["context"] = context
        return kwargs

    @classmethod
    def _latest_text(cls, messages: Sequence[BaseMessage]) -> str:
        if not messages:
            return ""
        return cls._content_to_text(messages[-1].content)

    @classmethod
    def _stream_chunk_text(cls, chunk: Any) -> str:
        if not isinstance(chunk, dict) or chunk.get("type") != "messages":
            return ""

        data = chunk.get("data")
        if not isinstance(data, tuple) or not data:
            return ""

        message_chunk = data[0]
        return cls._content_to_text(getattr(message_chunk, "content", ""))

    @staticmethod
    def _content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content

        if not isinstance(content, list):
            return ""

        text_parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(str(part.get("text", "")))

        return "".join(text_parts)
