import uuid
from collections.abc import AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base_agent import BaseAgent
from src.agents.echo_agent import EchoAgent
from src.db.database import async_session
from src.db.models import Conversation, Message, ToolCall
from src.schema.chat import ChatRequest
from src.utils.data_protocol import StreamProtocolBuilder


class ChatService:
    def __init__(self, request: ChatRequest):
        self.request = request
        self.agent: BaseAgent = EchoAgent()

    async def stream(self) -> AsyncGenerator[str, None]:
        """
        Full streaming pipeline in three phases:

        Phase 1 — DB setup (one session): get/create conversation, load history,
                   insert user + assistant placeholder rows, then commit and close.
        Phase 2 — Agent streaming (no session): iterate agent events, yield SSE,
                   accumulate text content and tool events.
        Phase 3 — DB finalisation (new session): update assistant message with
                   full content and status, persist any tool calls.
        """
        # ── Phase 1: DB setup ──────────────────────────────────────────────────
        try:
            async with async_session() as db:
                conversation_id, lc_messages, assistant_message_id = await self._setup(db)
        except ValueError as exc:
            yield StreamProtocolBuilder.error_part(str(exc), "not_found").to_sse()
            return

        # ── Phase 2: Streaming ─────────────────────────────────────────────────
        content_parts: list[str] = []
        tool_events: list[dict] = []

        try:
            async for ev in self.agent.iter_events(lc_messages):
                if ev["type"] == "text_delta":
                    content_parts.append(ev["content"])
                elif ev["type"] == "tool_end":
                    tool_events.append(ev)

                sse = BaseAgent.event_to_sse(ev)
                if sse is not None:
                    yield sse

            yield StreamProtocolBuilder.terminate_stream().to_sse()

            # ── Phase 3: DB finalisation ───────────────────────────────────────
            await self._finalize(
                assistant_message_id=assistant_message_id,
                content="".join(content_parts),
                tool_events=tool_events,
                status="completed",
            )

        except Exception as exc:
            yield StreamProtocolBuilder.error_part(str(exc), "stream_error").to_sse()
            await self._finalize(
                assistant_message_id=assistant_message_id,
                content=None,
                tool_events=[],
                status="failed",
            )

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _setup(self, db: AsyncSession) -> tuple[uuid.UUID, list, uuid.UUID]:
        """Create/validate conversation, load history, insert placeholder rows."""
        conversation_id = await self._get_or_create_conversation(db)
        history = await self._load_history(db, conversation_id)

        next_seq = len(history) + 1

        user_msg = Message(
            conversation_id=conversation_id,
            role="user",
            content=self.request.message,
            status="completed",
            sequence_number=next_seq,
        )
        db.add(user_msg)

        assistant_msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=None,
            status="streaming",
            sequence_number=next_seq + 1,
        )
        db.add(assistant_msg)
        await db.flush()
        await db.commit()

        lc_messages = self._to_lc_messages(history) + [HumanMessage(content=self.request.message)]
        return conversation_id, lc_messages, assistant_msg.id

    async def _get_or_create_conversation(self, db: AsyncSession) -> uuid.UUID:
        """Return existing conversation ID (validated) or create a new one."""
        if self.request.conversation_id:
            result = await db.execute(
                select(Conversation).where(
                    Conversation.id == uuid.UUID(self.request.conversation_id),
                    Conversation.user_id == self.request.user_id,
                )
            )
            conv = result.scalar_one_or_none()
            if conv is None:
                raise ValueError(
                    f"Conversation {self.request.conversation_id} not found for user {self.request.user_id}"
                )
            return conv.id

        conv = Conversation(user_id=self.request.user_id)
        db.add(conv)
        await db.flush()
        return conv.id

    async def _load_history(self, db: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
        result = await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.status == "completed",
                Message.role.in_(["user", "assistant"]),
            )
            .order_by(Message.sequence_number)
        )
        return list(result.scalars().all())

    @staticmethod
    def _to_lc_messages(history: list[Message]) -> list:
        lc: list = []
        for msg in history:
            if msg.role == "user":
                lc.append(HumanMessage(content=msg.content or ""))
            elif msg.role == "assistant":
                lc.append(AIMessage(content=msg.content or ""))
        return lc

    async def _finalize(
        self,
        assistant_message_id: uuid.UUID,
        content: str | None,
        tool_events: list[dict],
        status: str,
    ) -> None:
        """Update assistant message and persist any tool calls."""
        async with async_session() as db:
            await db.execute(
                update(Message)
                .where(Message.id == assistant_message_id)
                .values(content=content, status=status)
            )
            for ev in tool_events:
                db.add(
                    ToolCall(
                        message_id=assistant_message_id,
                        tool_call_id=ev["tool_call_id"],
                        tool_name=ev.get("tool_name", ""),
                        tool_input=ev.get("tool_input", {}),
                        tool_output=ev.get("tool_output", {}),
                    )
                )
            await db.commit()
