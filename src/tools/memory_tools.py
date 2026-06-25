"""LangChain tools for user-scoped long-term memory."""

from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from sqlalchemy.exc import SQLAlchemyError

from src.database import get_sessionmaker
from src.services.memory_service import (
    MemoryNotFoundError,
    MemoryService,
    MemoryValidationError,
    memory_payload,
    schedule_memory_commit,
)


@tool
async def memory_context(
    user_message: str,
    config: RunnableConfig,
    types: list[str] | None = None,
    tags: list[str] | None = None,
    max_items: int = 5,
) -> dict[str, Any]:
    """Fetch relevant remembered context for the current user message."""
    user_id = _user_id_from_config(config)
    if not user_id:
        return _missing_user_context()

    try:
        async with get_sessionmaker()() as session:
            service = MemoryService(session)
            return await service.memory_context(
                user_id=user_id,
                user_message=user_message,
                types=types,
                tags=tags,
                max_items=max_items,
            )
    except SQLAlchemyError as exc:
        return _storage_unavailable(exc)
    except MemoryValidationError as exc:
        return _tool_error("invalid_memory_request", str(exc))


@tool
async def memory_search(
    query: str,
    config: RunnableConfig,
    type: str | None = None,
    tags: list[str] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Search the current user's long-term memories."""
    user_id = _user_id_from_config(config)
    if not user_id:
        return _missing_user_context()

    try:
        async with get_sessionmaker()() as session:
            service = MemoryService(session)
            results = await service.search_memories(
                user_id=user_id,
                query=query,
                type=type,
                tags=tags,
                limit=limit,
            )
    except SQLAlchemyError as exc:
        return _storage_unavailable(exc)
    except MemoryValidationError as exc:
        return _tool_error("invalid_memory_request", str(exc))

    if not results:
        return {
            "status": "not_found",
            "results": [],
            "message": "No relevant memory found for this query.",
        }

    return {
        "status": "found",
        "results": [
            memory_payload(result.memory, similarity=result.similarity) for result in results
        ],
    }


@tool
async def memory_commit(
    type: str,
    summary: str,
    config: RunnableConfig,
    tags: list[str] | None = None,
    confidence: float = 0.8,
    source_message_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Save a short, stable, reusable memory for the current user."""
    user_id = _user_id_from_config(config)
    if not user_id:
        return _missing_user_context()

    try:
        memory = schedule_memory_commit(
            user_id=user_id,
            type=type,
            summary=summary,
            tags=tags,
            confidence=confidence,
            source_message_ids=source_message_ids,
            metadata=metadata,
        )
    except MemoryValidationError as exc:
        return _tool_error("invalid_memory_request", str(exc))

    if memory.get("status") == "error":
        return _tool_error(str(memory.get("error")), "Memory commit could not be queued.")

    return {
        "status": "queued",
        "memory": memory,
        "embedding_status": "queued_after_commit",
    }


@tool
async def memory_supersede(
    memory_id: str,
    reason: str,
    config: RunnableConfig,
    replaced_by_memory_id: str | None = None,
) -> dict[str, Any]:
    """Mark one of the current user's memories as superseded."""
    user_id = _user_id_from_config(config)
    if not user_id:
        return _missing_user_context()

    try:
        async with get_sessionmaker()() as session:
            service = MemoryService(session)
            memory = await service.supersede_memory(
                user_id=user_id,
                memory_id=memory_id,
                reason=reason,
                replaced_by_memory_id=replaced_by_memory_id,
            )
    except SQLAlchemyError as exc:
        return _storage_unavailable(exc)
    except MemoryNotFoundError:
        return {
            "status": "not_found",
            "memory_id": memory_id,
            "message": "Memory was not found for the current user.",
        }
    except MemoryValidationError as exc:
        return _tool_error("invalid_memory_request", str(exc))

    return {
        "status": "superseded",
        "memory_id": memory.id,
        "replaced_by_memory_id": replaced_by_memory_id,
    }


def _user_id_from_config(config: RunnableConfig | None) -> str | None:
    """Read the trusted runtime user id hidden from the model-facing schema."""
    if not isinstance(config, dict):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return None
    user_id = configurable.get("user_id")
    return str(user_id).strip() if user_id else None


def _missing_user_context() -> dict[str, Any]:
    return {
        "status": "error",
        "error": "missing_user_context",
        "message": "Memory tools require user_id from runtime context.",
    }


def _storage_unavailable(exc: SQLAlchemyError) -> dict[str, Any]:
    return {
        "status": "error",
        "error": "memory_storage_unavailable",
        "message": "Memory storage is unavailable. Continue without saved memory.",
        "detail": exc.__class__.__name__,
    }


def _tool_error(error: str, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": error,
        "message": message,
    }
