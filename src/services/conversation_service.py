"""Service layer for conversation CRUD operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import (
    Conversation,
    ConversationMessage,
    ConversationMessageReasoning,
    ConversationMessageToolCall,
)
from src.models.common import utc_now
from src.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
    MessageUpdate,
    ReasoningCreate,
    ReasoningUpdate,
    ToolCallCreate,
    ToolCallUpdate,
)


class ConversationNotFoundError(Exception):
    """Raised when a conversation cannot be found."""


class MessageNotFoundError(Exception):
    """Raised when a conversation message cannot be found."""


class ToolCallNotFoundError(Exception):
    """Raised when a message tool call cannot be found."""


class ReasoningNotFoundError(Exception):
    """Raised when a message reasoning entry cannot be found."""


class ConversationService:
    """CRUD service for conversations and messages."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the service with a database session."""
        self.session = session

    async def list_conversations(self, user_id: str | None = None) -> list[Conversation]:
        """List all conversations."""
        statement = select(Conversation)
        if user_id:
            statement = statement.where(Conversation.user_id == user_id)
        result = await self.session.execute(statement.order_by(Conversation.updated_at.desc()))
        return list(result.scalars().all())

    async def create_conversation(self, payload: ConversationCreate) -> Conversation:
        """Create a conversation."""
        conversation = Conversation(user_id=payload.user_id, title=payload.title)
        self.session.add(conversation)
        await self.session.commit()
        await self.session.refresh(conversation)
        return conversation

    async def get_conversation(self, conversation_id: str) -> Conversation:
        """Get a conversation by id."""
        conversation = await self.session.get(Conversation, conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        return conversation

    async def get_conversation_with_messages(self, conversation_id: str) -> Conversation:
        """Get a conversation by id with messages loaded."""
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(
                selectinload(Conversation.messages).selectinload(ConversationMessage.tool_calls),
                selectinload(Conversation.messages).selectinload(
                    ConversationMessage.reasoning_entries
                ),
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        return conversation

    async def update_conversation(
        self,
        conversation_id: str,
        payload: ConversationUpdate,
    ) -> Conversation:
        """Update a conversation."""
        conversation = await self.get_conversation(conversation_id)
        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(conversation, field, value)

        await self.session.commit()
        await self.session.refresh(conversation)
        return conversation

    async def delete_conversation(self, conversation_id: str) -> None:
        """Delete a conversation."""
        conversation = await self.get_conversation(conversation_id)
        await self.session.delete(conversation)
        await self.session.commit()

    async def list_messages(self, conversation_id: str) -> list[ConversationMessage]:
        """List messages for a conversation."""
        await self.get_conversation(conversation_id)
        result = await self.session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .options(
                selectinload(ConversationMessage.tool_calls),
                selectinload(ConversationMessage.reasoning_entries),
            )
            .order_by(ConversationMessage.created_at.asc())
        )
        return list(result.scalars().all())

    async def create_message(
        self,
        conversation_id: str,
        payload: MessageCreate,
    ) -> ConversationMessage:
        """Create a message in a conversation."""
        conversation = await self.get_conversation(conversation_id)
        message = ConversationMessage(
            conversation_id=conversation_id,
            role=payload.role,
            text=payload.text,
            message_metadata=payload.metadata,
            tool_calls=[
                self._tool_call_from_payload(tool_call) for tool_call in payload.tool_calls
            ],
            reasoning_entries=[
                self._reasoning_from_payload(reasoning) for reasoning in payload.reasoning_entries
            ],
        )
        conversation.updated_at = utc_now()
        self.session.add(message)
        await self.session.commit()
        return await self.get_message(conversation_id, message.id)

    async def get_message(
        self,
        conversation_id: str,
        message_id: str,
    ) -> ConversationMessage:
        """Get a message by id inside a conversation."""
        result = await self.session.execute(
            select(ConversationMessage)
            .where(
                ConversationMessage.id == message_id,
                ConversationMessage.conversation_id == conversation_id,
            )
            .options(
                selectinload(ConversationMessage.tool_calls),
                selectinload(ConversationMessage.reasoning_entries),
            )
        )
        message = result.scalar_one_or_none()
        if message is None:
            raise MessageNotFoundError(message_id)
        return message

    async def update_message(
        self,
        conversation_id: str,
        message_id: str,
        payload: MessageUpdate,
    ) -> ConversationMessage:
        """Update a message."""
        message = await self.get_message(conversation_id, message_id)
        update_data = payload.model_dump(exclude_unset=True)
        if "metadata" in update_data:
            update_data["message_metadata"] = update_data.pop("metadata")

        for field, value in update_data.items():
            setattr(message, field, value)

        await self.touch_conversation(conversation_id)
        await self.session.commit()
        return await self.get_message(conversation_id, message_id)

    async def delete_message(self, conversation_id: str, message_id: str) -> None:
        """Delete a message."""
        message = await self.get_message(conversation_id, message_id)
        await self.touch_conversation(conversation_id)
        await self.session.delete(message)
        await self.session.commit()

    async def list_tool_calls(
        self,
        conversation_id: str,
        message_id: str,
    ) -> list[ConversationMessageToolCall]:
        """List tool calls for a message."""
        message = await self.get_message(conversation_id, message_id)
        return message.tool_calls

    async def create_tool_call(
        self,
        conversation_id: str,
        message_id: str,
        payload: ToolCallCreate,
    ) -> ConversationMessageToolCall:
        """Create a tool call for a message."""
        await self.get_message(conversation_id, message_id)
        tool_call = self._tool_call_from_payload(payload)
        tool_call.message_id = message_id
        self.session.add(tool_call)
        await self.touch_conversation(conversation_id)
        await self.session.commit()
        await self.session.refresh(tool_call)
        return tool_call

    async def get_tool_call(
        self,
        conversation_id: str,
        message_id: str,
        tool_call_id: str,
    ) -> ConversationMessageToolCall:
        """Get a tool call by id."""
        await self.get_message(conversation_id, message_id)
        result = await self.session.execute(
            select(ConversationMessageToolCall).where(
                ConversationMessageToolCall.id == tool_call_id,
                ConversationMessageToolCall.message_id == message_id,
            )
        )
        tool_call = result.scalar_one_or_none()
        if tool_call is None:
            raise ToolCallNotFoundError(tool_call_id)
        return tool_call

    async def update_tool_call(
        self,
        conversation_id: str,
        message_id: str,
        tool_call_id: str,
        payload: ToolCallUpdate,
    ) -> ConversationMessageToolCall:
        """Update a tool call."""
        tool_call = await self.get_tool_call(conversation_id, message_id, tool_call_id)
        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(tool_call, field, value)
        await self.touch_conversation(conversation_id)
        await self.session.commit()
        await self.session.refresh(tool_call)
        return tool_call

    async def delete_tool_call(
        self,
        conversation_id: str,
        message_id: str,
        tool_call_id: str,
    ) -> None:
        """Delete a tool call."""
        tool_call = await self.get_tool_call(conversation_id, message_id, tool_call_id)
        await self.touch_conversation(conversation_id)
        await self.session.delete(tool_call)
        await self.session.commit()

    async def list_reasoning_entries(
        self,
        conversation_id: str,
        message_id: str,
    ) -> list[ConversationMessageReasoning]:
        """List reasoning entries for a message."""
        message = await self.get_message(conversation_id, message_id)
        return message.reasoning_entries

    async def create_reasoning_entry(
        self,
        conversation_id: str,
        message_id: str,
        payload: ReasoningCreate,
    ) -> ConversationMessageReasoning:
        """Create a reasoning entry for a message."""
        await self.get_message(conversation_id, message_id)
        reasoning = self._reasoning_from_payload(payload)
        reasoning.message_id = message_id
        self.session.add(reasoning)
        await self.touch_conversation(conversation_id)
        await self.session.commit()
        await self.session.refresh(reasoning)
        return reasoning

    async def get_reasoning_entry(
        self,
        conversation_id: str,
        message_id: str,
        reasoning_id: str,
    ) -> ConversationMessageReasoning:
        """Get a reasoning entry by id."""
        await self.get_message(conversation_id, message_id)
        result = await self.session.execute(
            select(ConversationMessageReasoning).where(
                ConversationMessageReasoning.id == reasoning_id,
                ConversationMessageReasoning.message_id == message_id,
            )
        )
        reasoning = result.scalar_one_or_none()
        if reasoning is None:
            raise ReasoningNotFoundError(reasoning_id)
        return reasoning

    async def update_reasoning_entry(
        self,
        conversation_id: str,
        message_id: str,
        reasoning_id: str,
        payload: ReasoningUpdate,
    ) -> ConversationMessageReasoning:
        """Update a reasoning entry."""
        reasoning = await self.get_reasoning_entry(conversation_id, message_id, reasoning_id)
        update_data = payload.model_dump(exclude_unset=True)
        if "metadata" in update_data:
            update_data["reasoning_metadata"] = update_data.pop("metadata")
        for field, value in update_data.items():
            setattr(reasoning, field, value)
        await self.touch_conversation(conversation_id)
        await self.session.commit()
        await self.session.refresh(reasoning)
        return reasoning

    async def delete_reasoning_entry(
        self,
        conversation_id: str,
        message_id: str,
        reasoning_id: str,
    ) -> None:
        """Delete a reasoning entry."""
        reasoning = await self.get_reasoning_entry(conversation_id, message_id, reasoning_id)
        await self.touch_conversation(conversation_id)
        await self.session.delete(reasoning)
        await self.session.commit()

    async def touch_conversation(self, conversation_id: str) -> None:
        """Update a conversation timestamp."""
        conversation = await self.get_conversation(conversation_id)
        conversation.updated_at = utc_now()

    @staticmethod
    def _tool_call_from_payload(payload: ToolCallCreate) -> ConversationMessageToolCall:
        return ConversationMessageToolCall(
            tool_call_id=payload.tool_call_id,
            name=payload.name,
            arguments=payload.arguments,
            result=payload.result,
            status=payload.status,
            sequence=payload.sequence,
        )

    @staticmethod
    def _reasoning_from_payload(payload: ReasoningCreate) -> ConversationMessageReasoning:
        return ConversationMessageReasoning(
            content=payload.content,
            summary=payload.summary,
            reasoning_metadata=payload.metadata,
            sequence=payload.sequence,
        )
