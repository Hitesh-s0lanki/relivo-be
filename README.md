# relivo-be-server

FastAPI backend server for Relivo.

## Requirements

- Python 3.13
- [uv](https://docs.astral.sh/uv/) package manager

## Setup

```bash
uv sync
```

## Run

Set `ENVIRONMENT=development` or `ENVIRONMENT=production` in `.env`, then run:
```bash
python src/main.py
```

Server runs at `http://localhost:8000`

## Environment Variables

The app loads from a `.env` file or environment variables. All have defaults:

| Variable      | Default              | Description                         |
|---------------|----------------------|-------------------------------------|
| `APP_NAME`    | `relivo-be-server`   | Application name                    |
| `VERSION`     | `0.1.0`              | App version                         |
| `ENVIRONMENT` | `development`        | Runtime environment                 |
| `HOST`        | `127.0.0.1`          | Server host                         |
| `PORT`        | `8000`               | Server port                         |
| `RELOAD`      | based on environment | Override Uvicorn auto-reload toggle |
| `OPENAI_API_KEY` | unset             | Enables real model streaming when configured |
| `RELIVO_CHAT_MODEL` | `gpt-5-mini` | Reasoning-capable chat model used when `OPENAI_API_KEY` is set |
| `RELIVO_CHAT_REASONING_EFFORT` | `low` | Reasoning effort for the chat model |
| `RELIVO_CHAT_USE_RESPONSES_API` | `true` | Uses OpenAI Responses API mode for reasoning models |

## API

- `POST /chat` — stream an agent response with Server-Sent Events
- `/conversations` — CRUD for conversations and conversation messages
- `GET /docs` — Swagger UI
- `GET /redoc` — ReDoc

Open `http://localhost:8000/docs` for the full interactive API documentation.
See `docs/chat_request_api.md` for the chat request API contract.
See `docs/conversation_api.md` for the conversation API contract.

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"user_message":"Hello","thread_id":"user-123"}'
```

## Tests

```bash
uv run pytest tests/ -v
```
