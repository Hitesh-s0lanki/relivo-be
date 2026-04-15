"""Service layer for chat business logic."""

import logging
import uuid
from collections.abc import AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base_agent import BaseAgent
from src.agents.echo_agent import EchoAgent
from src.db.database import async_session
from src.db.models import Conversation, Message, ToolCall
from src.schema.chat import UserMessageRequest
from src.schema.conversation import ConversationStatus
from src.services.conversation_service import ConversationService
from src.utils.data_protocol import StreamProtocolBuilder
from src.utils.stream_registry import stream_registry

logger = logging.getLogger(__name__)


class ChatService:
    """Handles streaming chat with cancel and resume support."""

    def __init__(self, request: UserMessageRequest) -> None:
        self.request = request
        self.agent: BaseAgent = EchoAgent()
        self._conversation_service = ConversationService()

    async def stream(self) -> AsyncGenerator[str, None]:
        """
        Streaming pipeline:
        Phase 1 — Validate conversation + DB setup.
        Phase 2 — Run agent; publish each SSE chunk; check cancel on each event.
        Phase 3 — Finalise DB records + reset conversation status to ACTIVE.
        """
        # ── Phase 1 ──────────────────────────────────────────────────────────
        try:
            async with async_session() as db:
                conversation_id, lc_messages, assistant_message_id = await self._setup(db)
        except ValueError as exc:
            yield StreamProtocolBuilder.error_part(str(exc), "not_found").to_sse()
            yield StreamProtocolBuilder.terminate_stream().to_sse()
            return

        conv_id_str = str(conversation_id)

        await self._conversation_service.update_conversation_status(
            conv_id_str, int(ConversationStatus.STREAMING)
        )
        await stream_registry.register(conv_id_str)

        # ── Phase 2 ──────────────────────────────────────────────────────────
        content_parts: list[str] = []
        tool_events: list[dict] = []
        final_status = "failed"

        try:
            async for ev in self.agent.iter_events(lc_messages):
                if stream_registry.is_cancelled(conv_id_str):
                    break

                if ev["type"] == "text_delta":
                    content_parts.append(ev["content"])
                elif ev["type"] == "tool_end":
                    tool_events.append(ev)

                sse = BaseAgent.event_to_sse(ev)
                if sse is not None:
                    await stream_registry.publish(conv_id_str, sse)
                    yield sse

            if not stream_registry.is_cancelled(conv_id_str):
                final_status = "completed"

            terminate = StreamProtocolBuilder.terminate_stream().to_sse()
            await stream_registry.publish(conv_id_str, terminate)
            yield terminate

        except Exception:
            logger.exception("Error during agent stream for user %s", self.request.user_id)
            err = StreamProtocolBuilder.error_part(
                "An error occurred. Please try again.", "stream_error"
            ).to_sse()
            terminate = StreamProtocolBuilder.terminate_stream().to_sse()
            await stream_registry.publish(conv_id_str, err)
            await stream_registry.publish(conv_id_str, terminate)
            yield err
            yield terminate

        finally:
            await stream_registry.mark_done(conv_id_str)
            await stream_registry.unregister(conv_id_str)
            try:
                await self._finalize(
                    conversation_id=conversation_id,
                    assistant_message_id=assistant_message_id,
                    content="".join(content_parts) if final_status == "completed" else None,
                    tool_events=tool_events if final_status == "completed" else [],
                    status=final_status,
                )
            except Exception:
                logger.exception("Failed to finalize message %s", assistant_message_id)
            await self._conversation_service.update_conversation_status(
                conv_id_str, int(ConversationStatus.ACTIVE)
            )

    async def _setup(self, db: AsyncSession) -> tuple[uuid.UUID, list, uuid.UUID]:
        """Validate conversation, load history, insert user + assistant placeholder rows."""
        conversation_id = await self._validate_conversation(db)
        history = await self._load_history(db, conversation_id)
        next_seq = len(history) + 1

        user_msg = Message(
            conversation_id=conversation_id,
            role="user",
            content=self.request.user_message,
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

        lc_messages = self._to_lc_messages(history) + [
            HumanMessage(content=self.request.user_message)
        ]
        return conversation_id, lc_messages, assistant_msg.id

    async def _validate_conversation(self, db: AsyncSession) -> uuid.UUID:
        """Ensure conversation exists and belongs to the requesting user."""
        conv_uuid = uuid.UUID(self.request.conversation_id)
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conv_uuid,
                Conversation.user_id == self.request.user_id,
            )
        )
        conv = result.scalar_one_or_none()
        if conv is None:
            raise ValueError(
                f"Conversation {self.request.conversation_id} not found "
                f"for user {self.request.user_id}"
            )
        return conv.id

    async def _load_history(
        self, db: AsyncSession, conversation_id: uuid.UUID
    ) -> list[Message]:
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
        conversation_id: uuid.UUID,
        assistant_message_id: uuid.UUID,
        content: str | None,
        tool_events: list[dict],
        status: str,
    ) -> None:
        """Update assistant message + tool calls; reset conversation status to ACTIVE."""
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
