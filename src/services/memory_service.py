"""Service layer for user-scoped long-term memory."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_openai import OpenAIEmbeddings
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_sessionmaker
from src.models import Memory
from src.models.common import utc_now, uuid_str

logger = logging.getLogger(__name__)

ALLOWED_MEMORY_TYPES = {"preferences", "info", "extra"}
ALLOWED_MEMORY_STATUSES = {"active", "superseded", "deleted", "uncertain"}
DEFAULT_MEMORY_RAG_MIN_SIMILARITY = 0.75
DEFAULT_MEMORY_EMBEDDING_TIMEOUT_SECONDS = 1.5
DEFAULT_MEMORY_TEXT_MIN_SIMILARITY = 0.25
DEFAULT_MEMORY_SEARCH_LIMIT = 5
MAX_MEMORY_SUMMARY_CHARS = 800
MAX_MEMORY_LIMIT = 20
_MEMORY_EMBEDDING_TASKS: set[asyncio.Task[None]] = set()
_MEMORY_COMMIT_TASKS: set[asyncio.Task[None]] = set()


class MemoryValidationError(Exception):
    """Raised when a memory payload is invalid."""


class MemoryNotFoundError(Exception):
    """Raised when a user-scoped memory cannot be found."""


class MemoryEmbeddingProvider(Protocol):
    """Protocol for embedding providers used by memory retrieval."""

    async def aembed_query(self, text: str) -> list[float]:
        """Embed one query or summary string."""


@dataclass(frozen=True, slots=True)
class MemorySearchResult:
    """A memory plus optional retrieval score."""

    memory: Memory
    similarity: float | None = None


class MemoryService:
    """Manage summary memories and vector retrieval."""

    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: MemoryEmbeddingProvider | None = None,
        *,
        min_similarity: float | None = None,
    ) -> None:
        """Initialize the service with storage and embedding dependencies."""
        self.session = session
        self.embedding_provider = (
            embedding_provider
            if embedding_provider is not None
            else build_memory_embedding_provider()
        )
        self.min_similarity = (
            min_similarity
            if min_similarity is not None
            else memory_rag_min_similarity()
        )

    async def commit_memory(
        self,
        *,
        user_id: str,
        type: str,
        summary: str,
        tags: list[str] | None = None,
        confidence: float = 0.8,
        source_message_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        memory_id: str | None = None,
    ) -> tuple[Memory, str]:
        """Create a memory row and best-effort embedding."""
        memory_type = validate_memory_type(type)
        cleaned_summary = validate_summary(summary)
        cleaned_tags = normalize_tags(tags)
        cleaned_source_ids = normalize_string_list(source_message_ids)
        cleaned_confidence = clamp_confidence(confidence)

        memory = Memory(
            id=memory_id or uuid_str(),
            user_id=validate_user_id(user_id),
            type=memory_type,
            summary=cleaned_summary,
            tags=cleaned_tags,
            confidence=cleaned_confidence,
            source_message_ids=cleaned_source_ids,
            memory_metadata=metadata or {},
        )
        self.session.add(memory)
        await self.session.commit()
        await self.session.refresh(memory)

        embedding_status = schedule_memory_embedding(memory.id)
        return memory, embedding_status

    async def search_memories(
        self,
        *,
        user_id: str,
        query: str = "",
        type: str | None = None,
        types: list[str] | None = None,
        tags: list[str] | None = None,
        limit: int = DEFAULT_MEMORY_SEARCH_LIMIT,
        status: str = "active",
    ) -> list[MemorySearchResult]:
        """Search memories by vector similarity, falling back to SQL/text matching."""
        user_id = validate_user_id(user_id)
        memory_types = normalize_type_filters(type=type, types=types)
        cleaned_tags = normalize_tags(tags)
        limit = normalize_limit(limit)
        status = validate_memory_status(status)

        sql_results = await self._sql_search(
            user_id=user_id,
            query=query,
            types=memory_types,
            tags=cleaned_tags,
            limit=limit,
            status=status,
        )
        if sql_results:
            return sql_results

        if not await self._has_candidate_memories(
            user_id=user_id,
            types=memory_types,
            tags=cleaned_tags,
            status=status,
        ):
            return []

        if query.strip() and self.embedding_provider is not None:
            vector_results = await self._vector_search(
                user_id=user_id,
                query=query,
                types=memory_types,
                tags=cleaned_tags,
                limit=limit,
                status=status,
            )
            if vector_results is not None:
                return vector_results

        return []

    async def memory_context(
        self,
        *,
        user_id: str,
        user_message: str,
        types: list[str] | None = None,
        tags: list[str] | None = None,
        max_items: int = DEFAULT_MEMORY_SEARCH_LIMIT,
    ) -> dict[str, Any]:
        """Return a compact context summary for an agent turn."""
        results = await self.search_memories(
            user_id=user_id,
            query=user_message,
            types=types,
            tags=tags,
            limit=max_items,
        )
        if not results:
            return {
                "status": "not_found",
                "context_summary": "",
                "memories": [],
                "missing_context": [],
                "message": "No relevant memory found for this query.",
            }

        memories = [
            memory_payload(result.memory, similarity=result.similarity)
            for result in results
        ]
        return {
            "status": "found",
            "context_summary": " ".join(memory["summary"] for memory in memories),
            "memories": memories,
            "missing_context": [],
        }

    async def supersede_memory(
        self,
        *,
        user_id: str,
        memory_id: str,
        reason: str,
        replaced_by_memory_id: str | None = None,
    ) -> Memory:
        """Mark a memory as superseded, preserving audit metadata."""
        memory = await self.get_user_memory(user_id=user_id, memory_id=memory_id)
        metadata = dict(memory.memory_metadata or {})
        metadata["superseded_reason"] = validate_summary(reason, max_chars=1000)
        if replaced_by_memory_id:
            metadata["replaced_by_memory_id"] = replaced_by_memory_id

        memory.status = "superseded"
        memory.memory_metadata = metadata
        memory.updated_at = utc_now()
        await self.session.commit()
        await self.session.refresh(memory)
        return memory

    async def get_user_memory(self, *, user_id: str, memory_id: str) -> Memory:
        """Fetch a memory by id, scoped to a user."""
        result = await self.session.execute(
            select(Memory).where(
                Memory.id == memory_id,
                Memory.user_id == validate_user_id(user_id),
            )
        )
        memory = result.scalar_one_or_none()
        if memory is None:
            raise MemoryNotFoundError(memory_id)
        return memory

    async def _store_embedding_best_effort(self, memory: Memory) -> str:
        if self.embedding_provider is None:
            return "skipped_no_embedding_provider"

        try:
            embedding = await self.embedding_provider.aembed_query(memory.summary)
            await self.session.execute(
                text(
                    """
                    INSERT INTO memory_embeddings (
                        id, user_id, memory_id, embedding, created_at
                    )
                    VALUES (
                        :id, :user_id, :memory_id, CAST(:embedding AS vector), :created_at
                    )
                    """
                ),
                {
                    "id": uuid_str(),
                    "user_id": memory.user_id,
                    "memory_id": memory.id,
                    "embedding": vector_literal(embedding),
                    "created_at": utc_now(),
                },
            )
            await self.session.commit()
            return "stored"
        except Exception as exc:
            await self.session.rollback()
            logger.warning("Failed to store memory embedding memory_id=%s: %s", memory.id, exc)
            return "failed"

    async def _vector_search(
        self,
        *,
        user_id: str,
        query: str,
        types: list[str],
        tags: list[str],
        limit: int,
        status: str,
    ) -> list[MemorySearchResult] | None:
        try:
            assert self.embedding_provider is not None
            embedding = await asyncio.wait_for(
                self.embedding_provider.aembed_query(query),
                timeout=memory_embedding_timeout_seconds(),
            )
            result = await self.session.execute(
                text(
                    """
                    SELECT
                        m.id,
                        1 - (e.embedding <=> CAST(:embedding AS vector)) AS similarity
                    FROM memories m
                    JOIN memory_embeddings e ON e.memory_id = m.id
                    WHERE m.user_id = :user_id
                        AND m.status = :status
                        AND 1 - (e.embedding <=> CAST(:embedding AS vector)) >= :min_similarity
                    ORDER BY similarity DESC, m.confidence DESC, m.updated_at DESC
                    LIMIT :candidate_limit
                    """
                ),
                {
                    "embedding": vector_literal(embedding),
                    "user_id": user_id,
                    "status": status,
                    "min_similarity": self.min_similarity,
                    "candidate_limit": max(limit * 5, limit),
                },
            )
            rows = result.mappings().all()
        except Exception as exc:
            logger.warning("Memory vector search failed; falling back to SQL search: %s", exc)
            await self.session.rollback()
            return None

        if not rows:
            return []

        memory_ids = [str(row["id"]) for row in rows]
        memories = await self._memories_by_ids(user_id=user_id, memory_ids=memory_ids)
        by_id = {memory.id: memory for memory in memories}
        ranked: list[MemorySearchResult] = []
        for row in rows:
            memory = by_id.get(str(row["id"]))
            if memory is None:
                continue
            if types and memory.type not in types:
                continue
            if not tags_match(memory.tags, tags):
                continue
            ranked.append(MemorySearchResult(memory=memory, similarity=float(row["similarity"])))
            if len(ranked) >= limit:
                break
        return ranked

    async def _sql_search(
        self,
        *,
        user_id: str,
        query: str,
        types: list[str],
        tags: list[str],
        limit: int,
        status: str,
    ) -> list[MemorySearchResult]:
        statement = select(Memory).where(Memory.user_id == user_id, Memory.status == status)
        if types:
            statement = statement.where(Memory.type.in_(types))
        result = await self.session.execute(statement.order_by(Memory.updated_at.desc()))
        memories = [
            memory
            for memory in result.scalars().all()
            if tags_match(memory.tags, tags)
        ]
        scored = [
            MemorySearchResult(memory=memory, similarity=text_similarity(query, memory))
            for memory in memories
        ]
        if query.strip():
            scored = [
                result
                for result in scored
                if (result.similarity or 0) >= DEFAULT_MEMORY_TEXT_MIN_SIMILARITY
            ]
        scored.sort(
            key=lambda item: (
                item.similarity or 0,
                item.memory.confidence,
                item.memory.updated_at,
            ),
            reverse=True,
        )
        return scored[:limit]

    async def _has_candidate_memories(
        self,
        *,
        user_id: str,
        types: list[str],
        tags: list[str],
        status: str,
    ) -> bool:
        """Return whether any memories could satisfy filters before vector search."""
        statement = select(func.count()).select_from(Memory).where(
            Memory.user_id == user_id,
            Memory.status == status,
        )
        if types:
            statement = statement.where(Memory.type.in_(types))
        result = await self.session.execute(statement)
        if int(result.scalar_one() or 0) == 0:
            return False

        if not tags:
            return True

        filtered = await self._sql_search(
            user_id=user_id,
            query="",
            types=types,
            tags=tags,
            limit=1,
            status=status,
        )
        return bool(filtered)

    async def _memories_by_ids(self, *, user_id: str, memory_ids: list[str]) -> list[Memory]:
        if not memory_ids:
            return []
        result = await self.session.execute(
            select(Memory).where(Memory.user_id == user_id, Memory.id.in_(memory_ids))
        )
        return list(result.scalars().all())


def build_memory_embedding_provider() -> MemoryEmbeddingProvider | None:
    """Build the configured embedding provider, or return None when unavailable."""
    if not os.getenv("OPENAI_API_KEY"):
        return None

    return OpenAIEmbeddings(
        model=os.getenv("MEMORY_EMBEDDING_MODEL", "text-embedding-3-small"),
        dimensions=int(os.getenv("MEMORY_EMBEDDING_DIMENSIONS", "1536")),
    )


def schedule_memory_embedding(memory_id: str) -> str:
    """Queue embedding storage for a memory without blocking tool completion."""
    if not os.getenv("OPENAI_API_KEY"):
        return "skipped_no_embedding_provider"

    try:
        task = asyncio.create_task(store_memory_embedding(memory_id))
    except RuntimeError:
        return "failed_no_event_loop"

    _MEMORY_EMBEDDING_TASKS.add(task)
    task.add_done_callback(_MEMORY_EMBEDDING_TASKS.discard)
    return "queued"


def schedule_memory_commit(
    *,
    user_id: str,
    type: str,
    summary: str,
    tags: list[str] | None = None,
    confidence: float = 0.8,
    source_message_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Queue a memory write and return a reserved memory payload immediately."""
    memory_id = uuid_str()
    cleaned_user_id = validate_user_id(user_id)
    payload = {
        "memory_id": memory_id,
        "type": validate_memory_type(type),
        "summary": validate_summary(summary),
        "tags": normalize_tags(tags),
        "status": "queued",
        "confidence": clamp_confidence(confidence),
        "source_message_ids": normalize_string_list(source_message_ids),
        "metadata": metadata or {},
    }

    try:
        task = asyncio.create_task(
            commit_memory_background(
                memory_id=memory_id,
                user_id=cleaned_user_id,
                type=payload["type"],
                summary=payload["summary"],
                tags=payload["tags"],
                confidence=payload["confidence"],
                source_message_ids=payload["source_message_ids"],
                metadata=payload["metadata"],
            )
        )
    except RuntimeError:
        payload["status"] = "error"
        payload["error"] = "failed_no_event_loop"
        return payload

    _MEMORY_COMMIT_TASKS.add(task)
    task.add_done_callback(_MEMORY_COMMIT_TASKS.discard)
    return payload


async def commit_memory_background(
    *,
    memory_id: str,
    user_id: str,
    type: str,
    summary: str,
    tags: list[str],
    confidence: float,
    source_message_ids: list[str],
    metadata: dict[str, Any],
) -> None:
    """Commit a memory in the background."""
    try:
        async with get_sessionmaker()() as session:
            service = MemoryService(session)
            await service.commit_memory(
                memory_id=memory_id,
                user_id=user_id,
                type=type,
                summary=summary,
                tags=tags,
                confidence=confidence,
                source_message_ids=source_message_ids,
                metadata=metadata,
            )
    except Exception as exc:
        logger.warning("Background memory commit failed memory_id=%s: %s", memory_id, exc)


async def store_memory_embedding(memory_id: str) -> None:
    """Store one memory embedding in an isolated background DB session."""
    try:
        async with get_sessionmaker()() as session:
            memory = await session.get(Memory, memory_id)
            if memory is None:
                return
            service = MemoryService(session)
            await service._store_embedding_best_effort(memory)
    except Exception as exc:
        logger.warning("Background memory embedding failed memory_id=%s: %s", memory_id, exc)


def memory_rag_min_similarity() -> float:
    """Read the minimum semantic match threshold for memory retrieval."""
    raw_value = os.getenv("MEMORY_RAG_MIN_SIMILARITY", str(DEFAULT_MEMORY_RAG_MIN_SIMILARITY))
    try:
        value = float(raw_value)
    except ValueError:
        return DEFAULT_MEMORY_RAG_MIN_SIMILARITY
    return min(max(value, 0.0), 1.0)


def memory_embedding_timeout_seconds() -> float:
    """Read the max time search should wait for query embeddings."""
    raw_value = os.getenv(
        "MEMORY_EMBEDDING_TIMEOUT_SECONDS",
        str(DEFAULT_MEMORY_EMBEDDING_TIMEOUT_SECONDS),
    )
    try:
        value = float(raw_value)
    except ValueError:
        return DEFAULT_MEMORY_EMBEDDING_TIMEOUT_SECONDS
    return max(value, 0.1)


def validate_user_id(user_id: str) -> str:
    """Validate user id from trusted runtime context."""
    cleaned = str(user_id or "").strip()
    if not cleaned:
        raise MemoryValidationError("user_id is required")
    if len(cleaned) > 200:
        raise MemoryValidationError("user_id is too long")
    return cleaned


def validate_memory_type(memory_type: str) -> str:
    """Validate a memory type."""
    cleaned = str(memory_type or "").strip().lower()
    if cleaned not in ALLOWED_MEMORY_TYPES:
        raise MemoryValidationError("type must be preferences, info, or extra")
    return cleaned


def validate_memory_status(status: str) -> str:
    """Validate a memory status."""
    cleaned = str(status or "").strip().lower()
    if cleaned not in ALLOWED_MEMORY_STATUSES:
        raise MemoryValidationError("invalid memory status")
    return cleaned


def validate_summary(summary: str, *, max_chars: int = MAX_MEMORY_SUMMARY_CHARS) -> str:
    """Validate and normalize summary text."""
    cleaned = " ".join(str(summary or "").split())
    if not cleaned:
        raise MemoryValidationError("summary is required")
    if len(cleaned) > max_chars:
        raise MemoryValidationError(f"summary must be {max_chars} characters or less")
    return cleaned


def normalize_tags(tags: list[str] | None) -> list[str]:
    """Normalize memory tags."""
    return normalize_string_list(tags, max_items=20, max_length=80)


def normalize_string_list(
    values: list[str] | None,
    *,
    max_items: int = 50,
    max_length: int = 200,
) -> list[str]:
    """Normalize a list of short strings."""
    if not values:
        return []
    cleaned: list[str] = []
    for value in values:
        item = str(value or "").strip().lower()
        if not item or item in cleaned:
            continue
        cleaned.append(item[:max_length])
        if len(cleaned) >= max_items:
            break
    return cleaned


def clamp_confidence(confidence: float) -> float:
    """Clamp confidence to the stored range."""
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        value = 0.8
    return min(max(value, 0.0), 1.0)


def normalize_limit(limit: int) -> int:
    """Normalize a tool-provided limit."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = DEFAULT_MEMORY_SEARCH_LIMIT
    return min(max(value, 1), MAX_MEMORY_LIMIT)


def normalize_type_filters(type: str | None, types: list[str] | None) -> list[str]:
    """Normalize singular and plural memory type filters."""
    raw_types = list(types or [])
    if type:
        raw_types.append(type)
    normalized: list[str] = []
    for raw_type in raw_types:
        memory_type = validate_memory_type(raw_type)
        if memory_type not in normalized:
            normalized.append(memory_type)
    return normalized


def tags_match(memory_tags: list[str] | None, required_tags: list[str]) -> bool:
    """Return whether a memory has all requested tags."""
    if not required_tags:
        return True
    normalized_memory_tags = set(normalize_tags(memory_tags))
    return all(tag in normalized_memory_tags for tag in required_tags)


def text_similarity(query: str, memory: Memory) -> float:
    """Return a lightweight lexical score for SQL fallback results."""
    query_terms = set(re.findall(r"[a-zA-Z0-9_]+", query.lower()))
    if not query_terms:
        return 1.0
    haystack = " ".join([memory.summary, memory.type, *normalize_tags(memory.tags)]).lower()
    matched = sum(1 for term in query_terms if term in haystack)
    return matched / len(query_terms)


def vector_literal(embedding: list[float]) -> str:
    """Format an embedding list for pgvector casts."""
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"


def memory_payload(memory: Memory, *, similarity: float | None = None) -> dict[str, Any]:
    """Serialize a memory for tool output."""
    payload: dict[str, Any] = {
        "memory_id": memory.id,
        "type": memory.type,
        "summary": memory.summary,
        "tags": memory.tags or [],
        "status": memory.status,
        "confidence": memory.confidence,
        "source_message_ids": memory.source_message_ids or [],
        "metadata": memory.memory_metadata or {},
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
    }
    if similarity is not None:
        payload["similarity"] = round(similarity, 4)
    return payload
