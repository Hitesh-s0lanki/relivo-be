"""Background extraction of reusable memories from chat turns."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from src.database import get_sessionmaker
from src.models import Conversation, ConversationMessage
from src.services.memory_service import MemoryService

logger = logging.getLogger(__name__)

MemoryType = Literal["preferences", "info", "extra"]


class ExtractedMemory(BaseModel):
    """One memory candidate produced by the extractor."""

    type: MemoryType
    summary: str = Field(..., min_length=1, max_length=800)
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0, le=1)
    supersedes_memory_id: str | None = None


class MemoryExtractionResult(BaseModel):
    """Structured extractor response."""

    memories: list[ExtractedMemory] = Field(default_factory=list)


async def run_memory_extraction_for_chat_turn(
    *,
    conversation_id: str,
    user_message: str,
    assistant_text: str,
    agent_id: str,
) -> None:
    """Extract memories for a completed chat turn in an isolated DB session."""
    if not os.getenv("OPENAI_API_KEY"):
        return

    try:
        async with get_sessionmaker()() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None:
                return

            memory_service = MemoryService(session)
            existing_context = await memory_service.memory_context(
                user_id=conversation.user_id,
                user_message=user_message,
                max_items=8,
            )
            source_message_ids = await latest_source_message_ids(
                session=session,
                conversation_id=conversation_id,
                user_message=user_message,
            )
            result = await extract_memories(
                user_message=user_message,
                assistant_text=assistant_text,
                existing_context=existing_context,
                agent_id=agent_id,
            )

            for candidate in result.memories:
                memory, _embedding_status = await memory_service.commit_memory(
                    user_id=conversation.user_id,
                    type=candidate.type,
                    summary=candidate.summary,
                    tags=candidate.tags,
                    confidence=candidate.confidence,
                    source_message_ids=source_message_ids,
                    metadata={
                        "source": "background_extractor",
                        "agent_id": agent_id,
                        "conversation_id": conversation_id,
                    },
                )
                if candidate.supersedes_memory_id:
                    try:
                        await memory_service.supersede_memory(
                            user_id=conversation.user_id,
                            memory_id=candidate.supersedes_memory_id,
                            reason=f"Superseded by newly extracted memory: {memory.summary}",
                            replaced_by_memory_id=memory.id,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to supersede memory during extraction old=%s new=%s: %s",
                            candidate.supersedes_memory_id,
                            memory.id,
                            exc,
                        )
    except Exception as exc:
        logger.warning("Background memory extraction failed: %s", exc, exc_info=exc)


async def extract_memories(
    *,
    user_message: str,
    assistant_text: str,
    existing_context: dict[str, Any],
    agent_id: str,
) -> MemoryExtractionResult:
    """Use a small LLM pass to extract stable reusable memories."""
    model = ChatOpenAI(
        model=os.getenv("MEMORY_EXTRACT_MODEL", os.getenv("RELIVO_CHAT_MODEL", "gpt-5-mini")),
        reasoning_effort=os.getenv("MEMORY_EXTRACT_REASONING_EFFORT", "low"),
        use_responses_api=True,
    )
    response = await model.ainvoke(
        [
            SystemMessage(content=EXTRACTOR_SYSTEM_PROMPT),
            HumanMessage(
                content=json.dumps(
                    {
                        "agent_id": agent_id,
                        "user_message": user_message,
                        "assistant_text": assistant_text,
                        "existing_memory_context": existing_context,
                    },
                    ensure_ascii=False,
                )
            ),
        ]
    )
    return parse_extraction_result(content_to_text(response.content))


async def latest_source_message_ids(
    *,
    session: Any,
    conversation_id: str,
    user_message: str,
) -> list[str]:
    """Find the latest persisted user message id matching the current turn."""
    result = await session.execute(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.role == "user",
        )
        .order_by(ConversationMessage.created_at.desc())
        .limit(5)
    )
    for message in result.scalars().all():
        if (message.text or "").strip() == user_message.strip():
            return [message.id]
    return []


def parse_extraction_result(content: str) -> MemoryExtractionResult:
    """Parse and validate extractor JSON."""
    try:
        raw = json.loads(strip_json_fence(content))
        return MemoryExtractionResult.model_validate(raw)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        logger.warning("Failed to parse memory extraction result: %s", exc)
        return MemoryExtractionResult()


def content_to_text(content: Any) -> str:
    """Convert chat model content blocks into text."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if content.get("type") == "text":
            return str(content.get("text", ""))
        return json.dumps(content, ensure_ascii=False)
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            if item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif "text" in item:
                parts.append(str(item.get("text", "")))
    return "".join(parts)


def strip_json_fence(content: str) -> str:
    """Remove common Markdown fences around JSON responses."""
    stripped = content.strip()
    if stripped.startswith("```json"):
        stripped = stripped.removeprefix("```json").strip()
    elif stripped.startswith("```"):
        stripped = stripped.removeprefix("```").strip()
    if stripped.endswith("```"):
        stripped = stripped.removesuffix("```").strip()
    return stripped


EXTRACTOR_SYSTEM_PROMPT = """
You are Relivo Memory Extractor.

Return JSON only with this shape:
{"memories":[{"type":"preferences|info|extra","summary":"...","tags":[],"confidence":0.0,"supersedes_memory_id":null}]}

Extract memory only when it is stable, reusable, useful for future agent tasks, and clearly
supported by the user message or assistant-confirmed workflow. Do not extract temporary chat,
guesses, sensitive secrets, credentials, or unsupported assumptions.

Use type="preferences" for durable user preferences. Use type="info" for durable facts about
the user's business, project, tools, constraints, or goals. Use type="extra" only for useful
state that does not fit the first two categories.

If the user intentionally provides personal profile, identity, background, career, education,
skills, location, or biography details for future conversations, extract concise type="info"
memories. Do not extract private secrets, credentials, raw contact details, or government/payment
identifiers.

Write short factual summaries. If the current turn clearly replaces an existing memory supplied
in existing_memory_context, set supersedes_memory_id to that memory id; otherwise use null.
If there is nothing worth remembering, return {"memories":[]}.
""".strip()
