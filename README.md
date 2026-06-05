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

## API

- `GET /health` — health check
- `GET /docs` — Swagger UI
- `GET /redoc` — ReDoc

## Tests

```bash
uv run pytest tests/ -v
```
