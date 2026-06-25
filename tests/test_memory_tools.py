"""Tests for memory tools and helpers."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.services.memory_service import (
    MemoryValidationError,
    memory_payload,
    memory_rag_min_similarity,
    validate_memory_type,
)
from src.tools.memory_tools import (
    memory_commit,
    memory_context,
    memory_search,
    memory_supersede,
)


class FakeSessionContext:
    """Async context manager for fake DB sessions."""

    async def __aenter__(self):
        """Return a fake session."""
        return SimpleNamespace()

    async def __aexit__(self, *_args):
        """Exit the fake session context."""
        return None


class FakeMemoryService:
    """Fake service that records runtime user ids."""

    calls = []

    def __init__(self, _session):
        """Accept the fake session dependency."""
        pass

    async def memory_context(self, **kwargs):
        self.calls.append(("context", kwargs))
        return {"status": "found", "context_summary": "remembered", "memories": []}

    async def search_memories(self, **kwargs):
        self.calls.append(("search", kwargs))
        return [SimpleNamespace(memory=fake_memory("mem-search"), similarity=0.88)]

    async def supersede_memory(self, **kwargs):
        self.calls.append(("supersede", kwargs))
        return fake_memory(kwargs["memory_id"], status="superseded")


class FailingMemoryService:
    """Fake service that simulates unavailable memory storage."""

    def __init__(self, _session):
        """Accept the fake session dependency."""

    async def search_memories(self, **_kwargs):
        """Raise a storage-layer error."""
        raise SQLAlchemyError("relation memories does not exist")


def fake_memory(memory_id: str, status: str = "active") -> SimpleNamespace:
    """Build a fake memory object for serialization."""
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=memory_id,
        type="preferences",
        summary="User prefers concise Markdown.",
        tags=["output_format"],
        status=status,
        confidence=0.9,
        source_message_ids=["msg-1"],
        memory_metadata={},
        created_at=now,
        updated_at=now,
    )


@pytest.fixture(autouse=True)
def fake_memory_dependencies(monkeypatch):
    """Route tool DB/service dependencies to fakes."""
    FakeMemoryService.calls = []
    monkeypatch.setattr("src.tools.memory_tools.get_sessionmaker", lambda: FakeSessionContext)
    monkeypatch.setattr("src.tools.memory_tools.MemoryService", FakeMemoryService)
    monkeypatch.setattr(
        "src.tools.memory_tools.schedule_memory_commit",
        lambda **kwargs: {
            "memory_id": "queued-memory",
            "type": kwargs["type"],
            "summary": kwargs["summary"],
            "tags": kwargs.get("tags") or [],
            "status": "queued",
            "confidence": kwargs.get("confidence", 0.8),
            "source_message_ids": kwargs.get("source_message_ids") or [],
            "metadata": kwargs.get("metadata") or {},
        },
    )


def test_memory_tool_schemas_do_not_expose_user_id() -> None:
    """The model should never see user_id in memory tool inputs."""
    for tool in [memory_context, memory_search, memory_commit, memory_supersede]:
        assert "user_id" not in tool.args
        assert "config" not in tool.args


@pytest.mark.asyncio
async def test_memory_tools_read_user_id_from_runtime_config() -> None:
    """Memory tools should use trusted runtime context for user isolation."""
    config = {"configurable": {"user_id": "user-123"}}

    await memory_context.ainvoke({"user_message": "what do you know?"}, config=config)
    await memory_search.ainvoke({"query": "format preference"}, config=config)
    commit_result = await memory_commit.ainvoke(
        {"type": "preferences", "summary": "User prefers concise Markdown."},
        config=config,
    )
    await memory_supersede.ainvoke(
        {"memory_id": "mem-old", "reason": "preference changed"},
        config=config,
    )

    assert [call[0] for call in FakeMemoryService.calls] == [
        "context",
        "search",
        "supersede",
    ]
    assert all(call[1]["user_id"] == "user-123" for call in FakeMemoryService.calls)
    assert commit_result["status"] == "queued"
    assert commit_result["memory"]["memory_id"] == "queued-memory"
    assert "user_id" not in commit_result["memory"]


@pytest.mark.asyncio
async def test_memory_tool_missing_user_context_returns_safe_error() -> None:
    """Memory tools should fail closed when runtime user context is missing."""
    result = await memory_search.ainvoke({"query": "anything"})

    assert result == {
        "status": "error",
        "error": "missing_user_context",
        "message": "Memory tools require user_id from runtime context.",
    }
    assert FakeMemoryService.calls == []


@pytest.mark.asyncio
async def test_memory_tool_storage_error_returns_safe_error(monkeypatch) -> None:
    """Storage failures should not crash the agent stream."""
    monkeypatch.setattr("src.tools.memory_tools.MemoryService", FailingMemoryService)

    result = await memory_search.ainvoke(
        {"query": "anything"},
        config={"configurable": {"user_id": "user-123"}},
    )

    assert result == {
        "status": "error",
        "error": "memory_storage_unavailable",
        "message": "Memory storage is unavailable. Continue without saved memory.",
        "detail": "SQLAlchemyError",
    }


def test_memory_rag_threshold_defaults_to_75_percent(monkeypatch) -> None:
    """Memory RAG should require a 75 percent semantic match by default."""
    monkeypatch.delenv("MEMORY_RAG_MIN_SIMILARITY", raising=False)

    assert memory_rag_min_similarity() == 0.75


def test_memory_type_validation_allows_only_mvp_types() -> None:
    """Only the agreed MVP memory types should be valid."""
    assert validate_memory_type("preferences") == "preferences"

    with pytest.raises(MemoryValidationError):
        validate_memory_type("project")


def test_memory_payload_includes_similarity_when_available() -> None:
    """Tool memory payloads should include rounded similarity scores."""
    payload = memory_payload(fake_memory("mem-1"), similarity=0.87654)

    assert payload["memory_id"] == "mem-1"
    assert payload["similarity"] == 0.8765
