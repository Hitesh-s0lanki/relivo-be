# LangChain Streaming Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a LangGraph-based streaming agent, PostgreSQL persistence, and a `/chat` SSE endpoint to `relivo-be-server`.

**Architecture:** `BaseAgent` wraps LangGraph's `create_react_agent`, exposing `iter_events()` (structured internal events) and `stream()` (SSE strings). `ChatService` uses `iter_events()` to accumulate content and tool calls for DB persistence while yielding SSE to the client. The route returns a `StreamingResponse` wrapped with a heartbeat generator.

**Tech Stack:** FastAPI, LangGraph, langchain-openai, SQLAlchemy async, asyncpg, Alembic, pytest-asyncio

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify | Add new dependencies |
| `src/app_config.py` | Modify | Add `database_url`, `openai_api_key`, `openai_model` |
| `src/db/__init__.py` | Create | Empty |
| `src/db/base.py` | Create | `DeclarativeBase` |
| `src/db/database.py` | Create | `engine`, `async_session`, `get_db_session()` |
| `src/db/models.py` | Create | `Conversation`, `Message`, `ToolCall` ORM models |
| `alembic.ini` | Create | Alembic config (via `alembic init`) |
| `alembic/env.py` | Modify | Async engine + our metadata |
| `alembic/versions/001_initial.py` | Create | Initial schema migration |
| `src/utils/__init__.py` | Create | Empty |
| `src/utils/data_protocol.py` | Create | `SSEEvent`, `StreamProtocolBuilder` |
| `src/utils/heartbeat_wrapper.py` | Create | `add_heartbeat_to_stream()` |
| `src/agents/__init__.py` | Create | Empty |
| `src/agents/base_agent.py` | Create | `BaseAgent` — `iter_events()`, `stream()`, `event_to_sse()` |
| `src/agents/echo_agent.py` | Create | `EchoAgent` — no tools, simple prompt |
| `src/schema/chat.py` | Create | `ChatRequest` Pydantic model |
| `src/services/__init__.py` | Create | Empty |
| `src/services/chat_service.py` | Create | `ChatService.stream()` — DB + agent orchestration |
| `src/routes/chat.py` | Create | `POST /chat` route |
| `src/main.py` | Modify | Add `lifespan`, include chat router |
| `tests/test_data_protocol.py` | Create | Unit tests for SSE formatting |
| `tests/test_heartbeat_wrapper.py` | Create | Unit tests for heartbeat injection |
| `tests/test_base_agent.py` | Create | Unit tests for `BaseAgent.iter_events()` |
| `tests/test_chat_route.py` | Create | Integration tests for `/chat` endpoint |

---

## Task 1: Install Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add packages via uv**

```bash
cd /path/to/relivo-be-server
uv add langchain-openai langgraph langchain-core "sqlalchemy[asyncio]" asyncpg alembic
```

Expected: `uv.lock` updated, no errors.

- [ ] **Step 2: Verify packages installed**

```bash
uv run python -c "import langchain_openai, langgraph, sqlalchemy, asyncpg, alembic; print('OK')"
```

Expected output: `OK`

- [ ] **Step 3: Run existing tests to confirm nothing broke**

```bash
uv run pytest tests/ -v
```

Expected: all existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add langchain, langgraph, sqlalchemy, asyncpg, alembic dependencies"
```

---

## Task 2: Extend App Config

**Files:**
- Modify: `src/app_config.py`

- [ ] **Step 1: Add new settings**

Replace the entire content of `src/app_config.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "relivo-be-server"
    version: str = "0.1.0"
    environment: str = "development"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/relivo"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"


settings = Settings()
```

- [ ] **Step 2: Create `.env` file (not committed)**

```bash
cat > .env << 'EOF'
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/relivo
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o-mini
EOF
```

- [ ] **Step 3: Verify settings load**

```bash
uv run python -c "from src.app_config import settings; print(settings.openai_model)"
```

Expected output: `gpt-4o-mini`

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/app_config.py
git commit -m "feat: add database_url, openai_api_key, openai_model to settings"
```

---

## Task 3: DB Foundation (base + database modules)

**Files:**
- Create: `src/db/__init__.py`
- Create: `src/db/base.py`
- Create: `src/db/database.py`

- [ ] **Step 1: Create `src/db/__init__.py`**

```python
```
(empty file)

- [ ] **Step 2: Create `src/db/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

- [ ] **Step 3: Create `src/db/database.py`**

```python
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.app_config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def get_db_session():
    """Async context manager for a database session."""
    async with async_session() as session:
        yield session
```

- [ ] **Step 4: Verify import works**

```bash
uv run python -c "from src.db.database import async_session, get_db_session; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/db/
git commit -m "feat: add DB engine and session factory"
```

---

## Task 4: DB Models

**Files:**
- Create: `src/db/models.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_db_models.py`:

```python
import uuid
from src.db.models import Conversation, Message, ToolCall


def test_conversation_defaults():
    conv = Conversation(user_id="u1")
    assert conv.user_id == "u1"
    assert isinstance(conv.id, uuid.UUID)
    assert conv.metadata_ == {}


def test_message_defaults():
    msg = Message(
        conversation_id=uuid.uuid4(),
        role="user",
        content="hello",
        sequence_number=1,
    )
    assert msg.status == "completed"
    assert isinstance(msg.id, uuid.UUID)


def test_tool_call_fields():
    tc = ToolCall(
        message_id=uuid.uuid4(),
        tool_call_id="run_abc",
        tool_name="search",
        tool_input={"query": "test"},
        tool_output={"result": "found"},
    )
    assert tc.tool_name == "search"
    assert isinstance(tc.id, uuid.UUID)
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
uv run pytest tests/test_db_models.py -v
```

Expected: ImportError — `src.db.models` does not exist.

- [ ] **Step 3: Create `src/db/models.py`**

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # 'user' | 'assistant'
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="completed")  # streaming | completed | failed
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")
    tool_calls: Mapped[list["ToolCall"]] = relationship(
        "ToolCall", back_populates="message", cascade="all, delete-orphan"
    )


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    tool_call_id: Mapped[str] = mapped_column(String, nullable=False)
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    tool_input: Mapped[dict] = mapped_column(JSONB, default=dict)
    tool_output: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    message: Mapped["Message"] = relationship("Message", back_populates="tool_calls")
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_db_models.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/db/models.py tests/test_db_models.py
git commit -m "feat: add Conversation, Message, ToolCall SQLAlchemy models"
```

---

## Task 5: Alembic Setup and Initial Migration

**Files:**
- Create: `alembic.ini` (via alembic init)
- Modify: `alembic/env.py`
- Create: `alembic/versions/001_initial_schema.py`

- [ ] **Step 1: Initialize Alembic**

```bash
uv run alembic init alembic
```

Expected: `alembic/` directory + `alembic.ini` created.

- [ ] **Step 2: Edit `alembic/env.py`**

Replace the entire file with:

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.app_config import settings
from src.db.base import Base
from src.db import models  # noqa: F401 — registers all models with Base.metadata

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 3: Create the initial migration manually**

Create `alembic/versions/001_initial_schema.py`:

```python
"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-04-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.create_table(
        "tool_calls",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "message_id",
            UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_call_id", sa.String(), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("tool_input", JSONB(), nullable=False, server_default="{}"),
        sa.Column("tool_output", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("tool_calls")
    op.drop_table("messages")
    op.drop_index("ix_conversations_user_id", "conversations")
    op.drop_table("conversations")
```

- [ ] **Step 4: Run migration against local DB**

Make sure PostgreSQL is running and the DB exists, then:

```bash
uv run alembic upgrade head
```

Expected: `Running upgrade  -> 001, initial schema`

- [ ] **Step 5: Commit**

```bash
git add alembic/ alembic.ini
git commit -m "feat: add alembic config and initial schema migration"
```

---

## Task 6: SSE Protocol (StreamProtocolBuilder)

**Files:**
- Create: `src/utils/__init__.py`
- Create: `src/utils/data_protocol.py`
- Create: `tests/test_data_protocol.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_data_protocol.py`:

```python
import json
from src.utils.data_protocol import SSEEvent, StreamProtocolBuilder


def test_sse_event_dict_to_sse():
    event = SSEEvent({"type": "text-delta", "id": "t1", "delta": "hi"})
    result = event.to_sse()
    assert result == 'data: {"type": "text-delta", "id": "t1", "delta": "hi"}\n\n'


def test_sse_event_string_to_sse():
    event = SSEEvent("[DONE]")
    assert event.to_sse() == "data: [DONE]\n\n"


def test_message_start():
    sse = StreamProtocolBuilder.message_start("msg_1").to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "start", "messageId": "msg_1"}


def test_stream_text_start():
    sse = StreamProtocolBuilder.stream_text_start("t1").to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "text-start", "id": "t1"}


def test_stream_text_delta():
    sse = StreamProtocolBuilder.stream_text_delta("t1", "hello").to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "text-delta", "id": "t1", "delta": "hello"}


def test_stream_text_end():
    sse = StreamProtocolBuilder.stream_text_end("t1").to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "text-end", "id": "t1"}


def test_tool_input_start():
    sse = StreamProtocolBuilder.tool_input_start("call_1", "search").to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "tool-input-start", "toolCallId": "call_1", "toolName": "search"}


def test_tool_input_available():
    sse = StreamProtocolBuilder.tool_input_available("call_1", "search", {"q": "test"}).to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {
        "type": "tool-input-available",
        "toolCallId": "call_1",
        "toolName": "search",
        "input": {"q": "test"},
    }


def test_tool_output_available():
    sse = StreamProtocolBuilder.tool_output_available("call_1", {"result": "found"}).to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {
        "type": "tool-output-available",
        "toolCallId": "call_1",
        "output": {"result": "found"},
    }


def test_message_end():
    sse = StreamProtocolBuilder.message_end({"usage": 100}).to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "finish", "messageMetadata": {"usage": 100}}


def test_terminate_stream():
    sse = StreamProtocolBuilder.terminate_stream().to_sse()
    assert sse == "data: [DONE]\n\n"


def test_error_part():
    sse = StreamProtocolBuilder.error_part("something broke", "internal_error").to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "error", "errorText": "internal_error:something broke"}


def test_data_heartbeat():
    sse = StreamProtocolBuilder.data_custom("heartbeat", {"ts": 123}).to_sse()
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "data-heartbeat", "data": {"ts": 123}}
```

- [ ] **Step 2: Run to confirm they fail**

```bash
uv run pytest tests/test_data_protocol.py -v
```

Expected: ImportError — module does not exist.

- [ ] **Step 3: Create `src/utils/__init__.py`** (empty)

- [ ] **Step 4: Create `src/utils/data_protocol.py`**

```python
import json
from dataclasses import dataclass


@dataclass
class SSEEvent:
    data: dict | str

    def to_sse(self) -> str:
        if isinstance(self.data, str):
            return f"data: {self.data}\n\n"
        return f"data: {json.dumps(self.data)}\n\n"


class StreamProtocolBuilder:
    @staticmethod
    def message_start(message_id: str) -> SSEEvent:
        return SSEEvent({"type": "start", "messageId": message_id})

    @staticmethod
    def stream_text_start(text_id: str) -> SSEEvent:
        return SSEEvent({"type": "text-start", "id": text_id})

    @staticmethod
    def stream_text_delta(text_id: str, delta: str) -> SSEEvent:
        return SSEEvent({"type": "text-delta", "id": text_id, "delta": delta})

    @staticmethod
    def stream_text_end(text_id: str) -> SSEEvent:
        return SSEEvent({"type": "text-end", "id": text_id})

    @staticmethod
    def tool_input_start(tool_call_id: str, tool_name: str) -> SSEEvent:
        return SSEEvent({"type": "tool-input-start", "toolCallId": tool_call_id, "toolName": tool_name})

    @staticmethod
    def tool_input_available(tool_call_id: str, tool_name: str, input_obj: dict) -> SSEEvent:
        return SSEEvent({
            "type": "tool-input-available",
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "input": input_obj,
        })

    @staticmethod
    def tool_output_available(tool_call_id: str, output_obj: dict) -> SSEEvent:
        return SSEEvent({
            "type": "tool-output-available",
            "toolCallId": tool_call_id,
            "output": output_obj,
        })

    @staticmethod
    def message_end(metadata: dict) -> SSEEvent:
        return SSEEvent({"type": "finish", "messageMetadata": metadata})

    @staticmethod
    def terminate_stream() -> SSEEvent:
        return SSEEvent("[DONE]")

    @staticmethod
    def error_part(error_text: str, code: str) -> SSEEvent:
        return SSEEvent({"type": "error", "errorText": f"{code}:{error_text}"})

    @staticmethod
    def data_custom(suffix: str, data: dict) -> SSEEvent:
        return SSEEvent({"type": f"data-{suffix}", "data": data})
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
uv run pytest tests/test_data_protocol.py -v
```

Expected: 13 passed.

- [ ] **Step 6: Commit**

```bash
git add src/utils/ tests/test_data_protocol.py
git commit -m "feat: add StreamProtocolBuilder with Vercel AI SDK SSE protocol"
```

---

## Task 7: Heartbeat Wrapper

**Files:**
- Create: `src/utils/heartbeat_wrapper.py`
- Create: `tests/test_heartbeat_wrapper.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_heartbeat_wrapper.py`:

```python
import asyncio
import json
import pytest
from src.utils.heartbeat_wrapper import add_heartbeat_to_stream


async def simple_gen(*chunks):
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_passthrough_without_heartbeat():
    """Short stream completes before heartbeat interval fires."""
    gen = simple_gen("data: a\n\n", "data: b\n\n")
    results = []
    async for chunk in add_heartbeat_to_stream(gen, interval=10.0):
        results.append(chunk)
    assert results == ["data: a\n\n", "data: b\n\n"]


@pytest.mark.asyncio
async def test_heartbeat_injected_on_delay():
    """Heartbeat fires when generator pauses longer than interval."""
    async def slow_gen():
        yield "data: first\n\n"
        await asyncio.sleep(0.15)  # longer than our test interval
        yield "data: second\n\n"

    results = []
    async for chunk in add_heartbeat_to_stream(slow_gen(), interval=0.1):
        results.append(chunk)

    # first chunk + at least one heartbeat + second chunk
    assert results[0] == "data: first\n\n"
    assert results[-1] == "data: second\n\n"
    heartbeats = [r for r in results if "data-heartbeat" in r]
    assert len(heartbeats) >= 1
    hb_data = json.loads(heartbeats[0].removeprefix("data: ").strip())
    assert hb_data["type"] == "data-heartbeat"
    assert "timestamp" in hb_data["data"]
```

- [ ] **Step 2: Run to confirm they fail**

```bash
uv run pytest tests/test_heartbeat_wrapper.py -v
```

Expected: ImportError.

- [ ] **Step 3: Create `src/utils/heartbeat_wrapper.py`**

```python
import asyncio
import time
from collections.abc import AsyncGenerator

from src.utils.data_protocol import StreamProtocolBuilder

_SENTINEL = object()


async def add_heartbeat_to_stream(
    generator: AsyncGenerator[str, None],
    interval: float = 10.0,
) -> AsyncGenerator[str, None]:
    """
    Wrap an SSE generator and inject heartbeat events during inactivity.

    If no chunk is yielded for `interval` seconds, a heartbeat SSE event is
    injected to keep the HTTP connection alive. The heartbeat check runs every
    1 second.
    """
    queue: asyncio.Queue = asyncio.Queue()
    last_event_time = time.monotonic()

    async def _drain_generator():
        try:
            async for chunk in generator:
                await queue.put(chunk)
        finally:
            await queue.put(_SENTINEL)

    async def _heartbeat_monitor():
        while True:
            await asyncio.sleep(1.0)
            elapsed = time.monotonic() - last_event_time
            if elapsed >= interval:
                hb = StreamProtocolBuilder.data_custom(
                    "heartbeat",
                    {"timestamp": time.time(), "time_since_last_event": round(elapsed, 2)},
                ).to_sse()
                await queue.put(hb)

    gen_task = asyncio.create_task(_drain_generator())
    hb_task = asyncio.create_task(_heartbeat_monitor())

    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            last_event_time = time.monotonic()
            yield item
    finally:
        hb_task.cancel()
        gen_task.cancel()
        await asyncio.gather(gen_task, hb_task, return_exceptions=True)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_heartbeat_wrapper.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/utils/heartbeat_wrapper.py tests/test_heartbeat_wrapper.py
git commit -m "feat: add heartbeat wrapper that injects SSE keepalive events"
```

---

## Task 8: BaseAgent

**Files:**
- Create: `src/agents/__init__.py`
- Create: `src/agents/base_agent.py`
- Create: `tests/test_base_agent.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_base_agent.py`:

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage


def make_stream_event(event_type, node="agent", run_id="run_abc123", **data):
    return {
        "event": event_type,
        "name": "ChatOpenAI",
        "run_id": run_id,
        "metadata": {"langgraph_node": node},
        "data": data,
    }


def text_chunk(content):
    chunk = MagicMock()
    chunk.content = content
    return chunk


async def fake_astream_events(input_dict, **kwargs):
    yield make_stream_event("on_chat_model_stream", chunk=text_chunk("Hello"))
    yield make_stream_event("on_chat_model_stream", chunk=text_chunk(" world"))
    yield make_stream_event("on_chat_model_end")


@pytest.mark.asyncio
async def test_iter_events_text_only():
    from src.agents.base_agent import BaseAgent

    with patch("src.agents.base_agent.ChatOpenAI"), \
         patch("src.agents.base_agent.create_react_agent") as mock_create:

        mock_graph = MagicMock()
        mock_graph.astream_events = fake_astream_events
        mock_create.return_value = mock_graph

        agent = BaseAgent(model="gpt-4o-mini", system_prompt="You are helpful.", tools=[])
        events = []
        async for ev in agent.iter_events([HumanMessage(content="hi")]):
            events.append(ev)

    types = [e["type"] for e in events]
    assert "message_start" in types
    assert "text_start" in types
    assert types.count("text_delta") == 2
    assert "text_end" in types
    assert "message_end" in types

    deltas = [e["content"] for e in events if e["type"] == "text_delta"]
    assert deltas == ["Hello", " world"]


@pytest.mark.asyncio
async def test_iter_events_tool_call():
    from src.agents.base_agent import BaseAgent

    async def with_tool_events(input_dict, **kwargs):
        yield make_stream_event("on_tool_start", node="tools", run_id="tool_run_1",
                                input={"query": "weather"})
        yield make_stream_event("on_tool_end", node="tools", run_id="tool_run_1",
                                output="Sunny, 25°C")
        yield make_stream_event("on_chat_model_stream", chunk=text_chunk("It is sunny."))
        yield make_stream_event("on_chat_model_end")

    with patch("src.agents.base_agent.ChatOpenAI"), \
         patch("src.agents.base_agent.create_react_agent") as mock_create:

        mock_graph = MagicMock()
        mock_graph.astream_events = with_tool_events
        mock_create.return_value = mock_graph

        agent = BaseAgent(model="gpt-4o-mini", system_prompt="You are helpful.", tools=[])
        events = []
        async for ev in agent.iter_events([HumanMessage(content="weather?")]):
            events.append(ev)

    types = [e["type"] for e in events]
    assert "tool_start" in types
    assert "tool_end" in types

    tool_start = next(e for e in events if e["type"] == "tool_start")
    assert tool_start["tool_name"] == "ChatOpenAI"
    assert tool_start["tool_input"] == {"query": "weather"}

    tool_end = next(e for e in events if e["type"] == "tool_end")
    assert tool_end["tool_output"] == {"output": "Sunny, 25°C"}


@pytest.mark.asyncio
async def test_stream_yields_sse_strings():
    from src.agents.base_agent import BaseAgent

    with patch("src.agents.base_agent.ChatOpenAI"), \
         patch("src.agents.base_agent.create_react_agent") as mock_create:

        mock_graph = MagicMock()
        mock_graph.astream_events = fake_astream_events
        mock_create.return_value = mock_graph

        agent = BaseAgent(model="gpt-4o-mini", system_prompt="You are helpful.", tools=[])
        chunks = []
        async for chunk in agent.stream([HumanMessage(content="hi")]):
            chunks.append(chunk)

    assert all(c.startswith("data: ") for c in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"

    text_deltas = [
        json.loads(c.removeprefix("data: ").strip())
        for c in chunks
        if '"text-delta"' in c
    ]
    assert [td["delta"] for td in text_deltas] == ["Hello", " world"]


def test_event_to_sse_text_delta():
    from src.agents.base_agent import BaseAgent

    sse = BaseAgent.event_to_sse({"type": "text_delta", "text_id": "t1", "content": "hi"})
    assert sse is not None
    data = json.loads(sse.removeprefix("data: ").strip())
    assert data == {"type": "text-delta", "id": "t1", "delta": "hi"}


def test_event_to_sse_unknown_returns_none():
    from src.agents.base_agent import BaseAgent

    assert BaseAgent.event_to_sse({"type": "unknown_event"}) is None
```

- [ ] **Step 2: Run to confirm they fail**

```bash
uv run pytest tests/test_base_agent.py -v
```

Expected: ImportError.

- [ ] **Step 3: Create `src/agents/__init__.py`** (empty)

- [ ] **Step 4: Create `src/agents/base_agent.py`**

```python
import uuid
from collections.abc import AsyncGenerator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
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

        yield {"type": "message_end", "metadata": {}}

    async def stream(self, messages: list) -> AsyncGenerator[str, None]:
        """Convert iter_events output to SSE strings."""
        async for ev in self.iter_events(messages):
            sse = self.event_to_sse(ev)
            if sse:
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
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_base_agent.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/agents/ tests/test_base_agent.py
git commit -m "feat: add BaseAgent with LangGraph iter_events streaming and SSE conversion"
```

---

## Task 9: EchoAgent

**Files:**
- Create: `src/agents/echo_agent.py`

- [ ] **Step 1: Create `src/agents/echo_agent.py`**

```python
from src.agents.base_agent import BaseAgent
from src.app_config import settings

_SYSTEM_PROMPT = (
    "You are a helpful assistant. "
    "Respond clearly and concisely to what the user says."
)


class EchoAgent(BaseAgent):
    """Dummy agent with no tools. Used to validate the full streaming pipeline."""

    def __init__(self):
        super().__init__(
            model=settings.openai_model,
            system_prompt=_SYSTEM_PROMPT,
            tools=[],
        )
```

- [ ] **Step 2: Verify import**

```bash
uv run python -c "from src.agents.echo_agent import EchoAgent; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/agents/echo_agent.py
git commit -m "feat: add EchoAgent dummy agent"
```

---

## Task 10: ChatRequest Schema

**Files:**
- Create: `src/schema/chat.py`

- [ ] **Step 1: Create `src/schema/chat.py`**

```python
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(..., description="ID of the user making the request")
    conversation_id: str | None = Field(
        None,
        description="Existing conversation ID. If omitted, a new conversation is created.",
    )
    message: str = Field(..., min_length=1, description="The user's message text")
```

- [ ] **Step 2: Write a quick schema validation test**

Add to `tests/test_chat_route.py` (create the file now, we will add more tests in Task 12):

```python
import pytest
from pydantic import ValidationError
from src.schema.chat import ChatRequest


def test_chat_request_requires_user_id_and_message():
    req = ChatRequest(user_id="u1", message="hello")
    assert req.conversation_id is None


def test_chat_request_empty_message_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(user_id="u1", message="")
```

- [ ] **Step 3: Run**

```bash
uv run pytest tests/test_chat_route.py::test_chat_request_requires_user_id_and_message \
             tests/test_chat_route.py::test_chat_request_empty_message_rejected -v
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add src/schema/chat.py tests/test_chat_route.py
git commit -m "feat: add ChatRequest schema"
```

---

## Task 11: ChatService

**Files:**
- Create: `src/services/__init__.py`
- Create: `src/services/chat_service.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_chat_route.py`:

```python
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest
from src.schema.chat import ChatRequest


async def fake_iter_events(messages):
    yield {"type": "message_start", "message_id": "msg1"}
    yield {"type": "text_start", "text_id": "t1"}
    yield {"type": "text_delta", "text_id": "t1", "content": "Hi"}
    yield {"type": "text_delta", "text_id": "t1", "content": " there!"}
    yield {"type": "text_end", "text_id": "t1"}
    yield {"type": "message_end", "metadata": {}}


@pytest.mark.asyncio
async def test_chat_service_stream_yields_sse_and_done(tmp_path):
    from src.services.chat_service import ChatService

    request = ChatRequest(user_id="u1", message="hello")
    conv_id = uuid.uuid4()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = None  # no existing conversation
    mock_execute_result.scalars.return_value.all.return_value = []  # empty history
    mock_session.execute = AsyncMock(return_value=mock_execute_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_agent = MagicMock()
    mock_agent.iter_events = fake_iter_events

    chunks = []
    with patch("src.services.chat_service.async_session", return_value=mock_session), \
         patch("src.services.chat_service.EchoAgent", return_value=mock_agent):

        service = ChatService(request)
        async for chunk in service.stream():
            chunks.append(chunk)

    assert chunks[-1] == "data: [DONE]\n\n"
    text_deltas = [
        json.loads(c.removeprefix("data: ").strip())
        for c in chunks if '"text-delta"' in c
    ]
    assert [td["delta"] for td in text_deltas] == ["Hi", " there!"]
```

- [ ] **Step 2: Run to confirm it fails**

```bash
uv run pytest tests/test_chat_route.py::test_chat_service_stream_yields_sse_and_done -v
```

Expected: ImportError.

- [ ] **Step 3: Create `src/services/__init__.py`** (empty)

- [ ] **Step 4: Create `src/services/chat_service.py`**

```python
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from langchain_core.messages import AIMessage, HumanMessage

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
        Full streaming pipeline:
          Phase 1 — DB setup (create/validate conversation, load history, insert placeholder rows)
          Phase 2 — Agent streaming (yield SSE chunks, accumulate content)
          Phase 3 — DB finalisation (update assistant message with full content)
        """
        # ── Phase 1: DB setup ──────────────────────────────────────────────
        async with async_session() as db:
            conversation_id, lc_messages, assistant_message_id = await self._setup(db)

        # ── Phase 2: Streaming ────────────────────────────────────────────
        content_parts: list[str] = []
        tool_events: list[dict] = []

        try:
            async for ev in self.agent.iter_events(lc_messages):
                if ev["type"] == "text_delta":
                    content_parts.append(ev["content"])
                elif ev["type"] == "tool_end":
                    tool_events.append(ev)

                sse = BaseAgent.event_to_sse(ev)
                if sse:
                    yield sse

            yield StreamProtocolBuilder.terminate_stream().to_sse()

            # ── Phase 3: DB finalisation ──────────────────────────────────
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

    # ── Private helpers ────────────────────────────────────────────────────

    async def _setup(self, db: AsyncSession) -> tuple[uuid.UUID, list, uuid.UUID]:
        """Create/validate conversation, load history, insert user + assistant rows."""
        conversation_id = await self._get_or_create_conversation(db)
        history = await self._load_history(db, conversation_id)

        # Count existing messages for sequence numbering
        next_seq = len(history) + 1

        # Insert user message
        user_msg = Message(
            conversation_id=conversation_id,
            role="user",
            content=self.request.message,
            status="completed",
            sequence_number=next_seq,
        )
        db.add(user_msg)

        # Insert assistant placeholder
        assistant_msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=None,
            status="streaming",
            sequence_number=next_seq + 1,
        )
        db.add(assistant_msg)
        await db.flush()  # populate .id on both rows
        await db.commit()

        # Build LangChain message list from history + new user message
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

        # No conversation_id → create new
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
        lc = []
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
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_chat_route.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/services/ tests/test_chat_route.py
git commit -m "feat: add ChatService with DB-backed streaming and tool call persistence"
```

---

## Task 12: Chat Route

**Files:**
- Create: `src/routes/chat.py`

- [ ] **Step 1: Write failing route test**

Append to `tests/test_chat_route.py`:

```python
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock


async def minimal_stream():
    yield 'data: {"type": "start", "messageId": "m1"}\n\n'
    yield 'data: {"type": "text-start", "id": "t1"}\n\n'
    yield 'data: {"type": "text-delta", "id": "t1", "delta": "hi"}\n\n'
    yield 'data: {"type": "text-end", "id": "t1"}\n\n'
    yield 'data: {"type": "finish", "messageMetadata": {}}\n\n'
    yield "data: [DONE]\n\n"


def test_chat_endpoint_streams_sse():
    from src.main import app

    mock_service = MagicMock()
    mock_service.stream = minimal_stream

    with patch("src.routes.chat.ChatService", return_value=mock_service), \
         patch("src.routes.chat.add_heartbeat_to_stream", side_effect=lambda g, **kw: g):

        client = TestClient(app)
        response = client.post(
            "/chat",
            json={"user_id": "u1", "message": "hello"},
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    body = response.text
    assert "text-delta" in body
    assert "[DONE]" in body


def test_chat_endpoint_missing_user_id_returns_422():
    from src.main import app

    client = TestClient(app)
    response = client.post("/chat", json={"message": "hello"})
    assert response.status_code == 422


def test_chat_endpoint_empty_message_returns_422():
    from src.main import app

    client = TestClient(app)
    response = client.post("/chat", json={"user_id": "u1", "message": ""})
    assert response.status_code == 422
```

- [ ] **Step 2: Run to confirm they fail**

```bash
uv run pytest tests/test_chat_route.py::test_chat_endpoint_streams_sse \
             tests/test_chat_route.py::test_chat_endpoint_missing_user_id_returns_422 \
             tests/test_chat_route.py::test_chat_endpoint_empty_message_returns_422 -v
```

Expected: errors (route not registered yet).

- [ ] **Step 3: Create `src/routes/chat.py`**

```python
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.schema.chat import ChatRequest
from src.services.chat_service import ChatService
from src.utils.heartbeat_wrapper import add_heartbeat_to_stream

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("")
async def chat(request: ChatRequest) -> StreamingResponse:
    """
    Stream an agent response for the given user message.

    Returns a text/event-stream response following the Vercel AI SDK Data Stream protocol.
    Heartbeat events are injected every 10 seconds of inactivity.
    """
    service = ChatService(request)
    generator = add_heartbeat_to_stream(service.stream(), interval=10.0)
    return StreamingResponse(generator, media_type="text/event-stream")
```

- [ ] **Step 4: Register the router in `src/main.py`**

Replace `src/main.py` with:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.app_config import settings
from src.routes.health import router as health_router
from src.routes.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Future: add startup/shutdown logic here (e.g., DB connection pool warm-up)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(chat_router)
    return app


app = create_app()
```

- [ ] **Step 5: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass (includes health, model, protocol, heartbeat, agent, route tests).

- [ ] **Step 6: Commit**

```bash
git add src/routes/chat.py src/main.py tests/test_chat_route.py
git commit -m "feat: add /chat streaming endpoint with heartbeat and SSE response"
```

---

## Task 13: End-to-End Smoke Test

- [ ] **Step 1: Start the server**

```bash
uv run uvicorn src.main:app --reload
```

- [ ] **Step 2: Hit the health endpoint**

```bash
curl http://localhost:8000/health/
```

Expected:
```json
{"status": "ok", "version": "0.1.0", "environment": "development"}
```

- [ ] **Step 3: Send a chat request and verify SSE stream**

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test_user", "message": "Say hello in one sentence."}' \
  --no-buffer
```

Expected: a stream of `data: {...}` lines ending with `data: [DONE]`, with `"type":"text-delta"` events containing the agent's response.

- [ ] **Step 4: Verify conversation is persisted in DB**

```bash
uv run python -c "
import asyncio
from src.db.database import async_session
from src.db.models import Message
from sqlalchemy import select

async def check():
    async with async_session() as db:
        result = await db.execute(select(Message).order_by(Message.created_at.desc()).limit(2))
        for m in result.scalars().all():
            print(m.role, m.status, repr(m.content[:50] if m.content else None))

asyncio.run(check())
"
```

Expected: two rows — `user completed` and `assistant completed` with message content.

---

## Self-Review Against Spec

| Spec Requirement | Task |
|---|---|
| LangGraph `create_react_agent` | Task 8 |
| `BaseAgent.iter_events()` + `stream()` | Task 8 |
| `EchoAgent` (dummy agent, no tools) | Task 9 |
| Vercel AI SDK SSE protocol | Task 6 |
| Heartbeat wrapper (10s) | Task 7 |
| PostgreSQL schema: conversations + user_id | Task 4, 5 |
| PostgreSQL schema: messages (streaming → completed) | Task 4, 5 |
| PostgreSQL schema: tool_calls | Task 4, 5 |
| `POST /chat` endpoint | Task 12 |
| Load message history from DB | Task 11 |
| Persist user message at stream start | Task 11 |
| Persist assistant message placeholder (streaming) | Task 11 |
| Persist tool calls during stream | Task 11 |
| Update assistant message on stream end | Task 11 |
| Error SSE on failure + message status=failed | Task 11 |
| `user_id` required, `conversation_id` optional | Task 10, 11 |
| Alembic migrations | Task 5 |
