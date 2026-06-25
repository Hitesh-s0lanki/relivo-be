"""Base LangChain agent harness with streaming helpers."""

import warnings
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

warnings.filterwarnings(
    "ignore",
    message="The default value of `allowed_objects` will change in a future version.*",
    category=LangChainPendingDeprecationWarning,
)

from langchain.agents import create_agent  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import BaseMessage  # noqa: E402
from langchain_core.tools import BaseTool  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

AgentModel = str | BaseChatModel
AgentTool = BaseTool | Callable[..., Any] | dict[str, Any]
AgentPrompt = str | list[dict[str, Any]]
StreamMode = str | Sequence[str]
StreamVersion = Literal["v1", "v2"]


@dataclass(frozen=True, slots=True)
class BaseAgentConfig:
    """Configuration for the base LangChain agent harness."""

    model: AgentModel
    system_prompt: str = "You are a helpful assistant. Be concise, accurate, and direct."
    name: str = "base_agent"
    stream_version: StreamVersion = "v2"


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

    def invoke(
        self,
        prompt: AgentPrompt,
        *,
        thread_id: str = "default",
        context: Any | None = None,
    ) -> str:
        """Run one agent turn and return the final assistant text."""
        kwargs = self._run_kwargs(thread_id=thread_id, context=context)
        result = self.graph.invoke(self._messages_input(prompt), **kwargs)
        return self._latest_text(result["messages"])

    async def ainvoke(
        self,
        prompt: AgentPrompt,
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
        prompt: AgentPrompt,
        *,
        thread_id: str = "default",
        context: Any | None = None,
    ) -> Iterator[str]:
        """Yield assistant text chunks from a synchronous agent stream."""
        for chunk in self.graph.stream(
            self._messages_input(prompt),
            **self._stream_kwargs(
                thread_id=thread_id,
                context=context,
                stream_mode="messages",
            ),
        ):
            text = self._stream_chunk_text(chunk)
            if text:
                yield text

    def stream_events(
        self,
        prompt: AgentPrompt,
        *,
        thread_id: str = "default",
        context: Any | None = None,
        stream_mode: StreamMode = ("updates", "messages"),
    ) -> Iterator[Any]:
        """Yield the raw LangChain agent stream, including model/tool updates."""
        yield from self.graph.stream(
            self._messages_input(prompt),
            **self._stream_kwargs(
                thread_id=thread_id,
                context=context,
                stream_mode=stream_mode,
            ),
        )

    async def astream_text(
        self,
        prompt: AgentPrompt,
        *,
        thread_id: str = "default",
        context: Any | None = None,
    ) -> AsyncIterator[str]:
        """Yield assistant text chunks from an async agent stream."""
        async for chunk in self.graph.astream(
            self._messages_input(prompt),
            **self._stream_kwargs(
                thread_id=thread_id,
                context=context,
                stream_mode="messages",
            ),
        ):
            text = self._stream_chunk_text(chunk)
            if text:
                yield text

    async def astream_events(
        self,
        prompt: AgentPrompt,
        *,
        thread_id: str = "default",
        context: Any | None = None,
        stream_mode: StreamMode = ("updates", "messages"),
    ) -> AsyncIterator[Any]:
        """Yield the raw async LangChain agent stream, including model/tool updates."""
        async for chunk in self.graph.astream(
            self._messages_input(prompt),
            **self._stream_kwargs(
                thread_id=thread_id,
                context=context,
                stream_mode=stream_mode,
            ),
        ):
            yield chunk

    @staticmethod
    def _messages_input(prompt: AgentPrompt) -> dict[str, list[dict[str, Any]]]:
        return {"messages": [{"role": "user", "content": prompt}]}

    @staticmethod
    def _run_kwargs(thread_id: str, context: Any | None) -> dict[str, Any]:
        configurable: dict[str, Any] = {"thread_id": thread_id}
        if isinstance(context, dict):
            for key in ("user_id", "agent_id", "conversation_id"):
                value = context.get(key)
                if value is not None:
                    configurable[key] = value

        kwargs: dict[str, Any] = {"config": {"configurable": configurable}}
        if context is not None:
            kwargs["context"] = context
        return kwargs

    def _stream_kwargs(
        self,
        *,
        thread_id: str,
        context: Any | None,
        stream_mode: StreamMode,
    ) -> dict[str, Any]:
        """Build shared LangGraph stream kwargs."""
        return {
            **self._run_kwargs(thread_id=thread_id, context=context),
            "stream_mode": stream_mode,
            "version": self.config.stream_version,
        }

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
