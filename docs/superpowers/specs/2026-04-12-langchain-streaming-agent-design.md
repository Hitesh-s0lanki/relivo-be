# LangChain Streaming Agent — Design Spec
**Date:** 2026-04-12  
**Project:** relivo-be-server  
**Status:** Approved

---

## Overview

Implement a LangGraph-based agent system in `relivo-be-server` with full SSE streaming, PostgreSQL persistence, and a `/chat` endpoint. The streaming format follows the **Vercel AI SDK Data Stream protocol** (same as `strique-ai-server`). No Redis, no multi-agent handoffs, no agent registry. Message history is loaded from and persisted to PostgreSQL.

---

## Architecture

### File Structure

```
src/
├── main.py                        # Add lifespan, include chat router
├── app_config.py                  # Add DB_URL, OPENAI_API_KEY settings
├── agents/
│   ├── __init__.py
│   ├── base_agent.py              # BaseAgent wrapping LangGraph create_react_agent
│   └── echo_agent.py             # DummyAgent — no tools, simple system prompt
├── routes/
│   ├── health.py                  # (existing, untouched)
│   └── chat.py                    # POST /chat → StreamingResponse
├── schema/
│   ├── health.py                  # (existing, untouched)
│   └── chat.py                    # ChatRequest Pydantic model
├── db/
│   ├── database.py                # AsyncEngine, async_session_maker, get_db dependency
│   ├── base.py                    # DeclarativeBase
│   └── models.py                  # Conversation, Message, ToolCall ORM models
├── services/
│   └── chat_service.py            # Loads history, runs agent, persists to DB
└── utils/
    ├── data_protocol.py           # StreamProtocolBuilder (Vercel AI SSE format)
    └── heartbeat_wrapper.py       # Injects heartbeat every 10s of inactivity
```

### New Dependencies

| Package | Purpose |
|---|---|
| `langchain-openai` | `ChatOpenAI` LLM |
| `langgraph` | `create_react_agent`, graph streaming via `astream_events` |
| `langchain-core` | Base types (messages, tools) |
| `sqlalchemy[asyncio]` | Async ORM |
| `asyncpg` | Async PostgreSQL driver |
| `alembic` | Database migrations |

---

## Database Schema

### `conversations`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | `gen_random_uuid()` |
| `user_id` | TEXT NOT NULL | Indexed for per-user fetches |
| `title` | TEXT | Nullable |
| `metadata` | JSONB | Default `'{}'` |
| `created_at` | TIMESTAMPTZ | Default `NOW()` |
| `updated_at` | TIMESTAMPTZ | Default `NOW()` |

### `messages`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `conversation_id` | UUID FK | → `conversations.id` CASCADE DELETE |
| `role` | TEXT | `'user'` or `'assistant'` |
| `content` | TEXT | Null during streaming, populated on completion |
| `status` | TEXT | `'streaming'` → `'completed'` or `'failed'` |
| `sequence_number` | INTEGER | Ordering within conversation |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

### `tool_calls`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `message_id` | UUID FK | → `messages.id` CASCADE DELETE |
| `tool_call_id` | TEXT | LangGraph's internal tool call ID |
| `tool_name` | TEXT | |
| `tool_input` | JSONB | |
| `tool_output` | JSONB | |
| `created_at` | TIMESTAMPTZ | |

---

## Agent Design

### `BaseAgent` (`src/agents/base_agent.py`)

```python
class BaseAgent:
    def __init__(self, model: str, system_prompt: str, tools: list):
        self.llm = ChatOpenAI(model=model, streaming=True)
        self.tools = tools
        self.system_prompt = system_prompt
        self.graph = create_react_agent(self.llm, tools, prompt=system_prompt)

    async def stream(self, messages: list) -> AsyncGenerator[str, None]:
        """
        Accepts a list of LangChain message dicts.
        Yields SSE-formatted strings (Vercel AI SDK Data Stream protocol).
        """
        async for event in self.graph.astream_events(
            {"messages": messages}, version="v2"
        ):
            sse = self._map_event(event)
            if sse:
                yield sse
        yield StreamProtocolBuilder.terminate_stream().to_sse()

    def _map_event(self, event: dict) -> str | None:
        """Map LangGraph astream_events to Vercel AI SSE strings."""
        ...
```

### Event Mapping

| LangGraph `astream_events` event | SSE output |
|---|---|
| `on_chat_model_start` | `message_start` + `text_start` |
| `on_chat_model_stream` (text chunk) | `text_delta` |
| `on_chat_model_end` | `text_end` |
| `on_tool_start` | `tool_input_start` + `tool_input_available` |
| `on_tool_end` | `tool_output_available` |
| Stream complete | `message_end` + `[DONE]` |

### `EchoAgent` (`src/agents/echo_agent.py`)

```python
class EchoAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            model="gpt-4o-mini",
            system_prompt="You are a helpful assistant. Respond clearly and concisely.",
            tools=[],
        )
```

---

## `/chat` Endpoint

### Request
```json
POST /chat
{
  "user_id": "user_123",
  "conversation_id": "uuid-optional",
  "message": "Hello!"
}
```

### Response
`StreamingResponse` with `Content-Type: text/event-stream`

```
data: {"type":"start","messageId":"msg_abc"}\n\n
data: {"type":"text-start","id":"text_001"}\n\n
data: {"type":"text-delta","id":"text_001","delta":"Hello"}\n\n
data: {"type":"text-delta","id":"text_001","delta":" there!"}\n\n
data: {"type":"text-end","id":"text_001"}\n\n
data: {"type":"finish","messageMetadata":{}}\n\n
data: [DONE]\n\n
```

### Flow (`ChatService.chat`)

```
1. If no conversation_id → INSERT conversations row, return new id
2. Validate conversation exists + belongs to user_id
3. Load message history from DB (messages WHERE conversation_id ORDER BY sequence_number)
4. Build LangChain message list from history
5. Append new user message to list
6. INSERT messages row (role='user', status='completed', sequence_number=N)
7. INSERT messages row (role='assistant', status='streaming', sequence_number=N+1)
8. Run agent.stream(message_list)   ← EchoAgent in this implementation
   — on_tool_end → INSERT tool_calls row immediately
9. Wrap generator with heartbeat_wrapper
10. Return StreamingResponse(generator, media_type="text/event-stream")
11. On stream end (background): UPDATE messages SET content=<full_text>, status='completed'
    On stream error: UPDATE messages SET status='failed'
```

---

## Heartbeat Wrapper (`src/utils/heartbeat_wrapper.py`)

Wraps any `AsyncGenerator[str, None]`. If no event is yielded for 10 seconds, injects:
```
data: {"type":"data-heartbeat","data":{"timestamp":1234567890,"time_since_last_event":10.2}}\n\n
```
Keeps the HTTP connection alive during long tool calls or slow LLM responses.

---

## SSE Protocol (`src/utils/data_protocol.py`)

`StreamProtocolBuilder` — static methods returning `SSEEvent` objects with a `.to_sse()` method:

```python
StreamProtocolBuilder.message_start(message_id)     # {"type":"start","messageId":"..."}
StreamProtocolBuilder.stream_text_start(id)          # {"type":"text-start","id":"..."}
StreamProtocolBuilder.stream_text_delta(id, delta)   # {"type":"text-delta","id":"...","delta":"..."}
StreamProtocolBuilder.stream_text_end(id)            # {"type":"text-end","id":"..."}
StreamProtocolBuilder.tool_input_start(call_id, name)
StreamProtocolBuilder.tool_input_available(call_id, name, input_obj)
StreamProtocolBuilder.tool_output_available(call_id, output_obj)
StreamProtocolBuilder.message_end(metadata)          # {"type":"finish","messageMetadata":{...}}
StreamProtocolBuilder.terminate_stream()             # "[DONE]"
StreamProtocolBuilder.error_part(text, code)         # {"type":"error","errorText":"code:text"}

# SSEEvent.to_sse() → "data: {json}\n\n"
```

---

## Configuration (`src/app_config.py` additions)

```python
DATABASE_URL: str          # postgresql+asyncpg://...
OPENAI_API_KEY: str
OPENAI_MODEL: str = "gpt-4o-mini"
```

---

## Error Handling

- Missing `user_id` → 400 (`user_id` is always required; `conversation_id` is optional — omitting it starts a new conversation)
- `conversation_id` provided but not found or not owned by `user_id` → 404
- LLM / LangGraph error mid-stream → yield `error_part` SSE + update message status to `failed`
- Unhandled exception in route → 500 JSON response

---

## Out of Scope

- Authentication / auth middleware
- Multi-agent handoffs
- Redis stream registry / resume-stream / cancel endpoint
- Stream cancellation
- Rate limiting
- Token usage tracking
