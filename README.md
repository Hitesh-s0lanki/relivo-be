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

**Development (with auto-reload):**
```bash
uv run uvicorn src.main:app --reload
```

**Production:**
```bash
uv run uvicorn src.main:app
```

Server runs at `http://localhost:8000`

## Environment Variables

The app loads from a `.env` file or environment variables. All have defaults:

| Variable      | Default              | Description        |
|---------------|----------------------|--------------------|
| `APP_NAME`    | `relivo-be-server`   | Application name   |
| `VERSION`     | `0.1.0`              | App version        |
| `ENVIRONMENT` | `development`        | Runtime environment |

## API

- `GET /health` — health check
- `GET /docs` — Swagger UI
- `GET /redoc` — ReDoc

## Tests

```bash
uv run pytest tests/ -v
```
