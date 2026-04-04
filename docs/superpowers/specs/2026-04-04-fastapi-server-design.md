# FastAPI Server Design — relivo-be-server

**Date:** 2026-04-04  
**Status:** Approved

---

## Overview

Bootstrap a FastAPI backend server for the `relivo-be-server` project using a modular `src/` layout. The server uses `pydantic-settings` for configuration, Pydantic v2 models for all response schemas, and `uvicorn` as the ASGI server.

---

## Architecture

All application code lives under `src/`. The entry point (`main.py`) creates the FastAPI app, loads config, and mounts routers. Routes and schemas are separate sub-packages.

```
src/
├── main.py              # App factory: creates FastAPI instance, mounts routers
├── app_config.py        # Settings loaded from environment via pydantic-settings
├── routes/
│   ├── __init__.py
│   └── health.py        # GET /health → HealthResponse
└── schema/
    ├── __init__.py
    └── health.py        # HealthResponse Pydantic model
```

---

## Components

### `app_config.py`
- `Settings` class extending `pydantic_settings.BaseSettings`
- Fields: `app_name: str`, `version: str`, `environment: str` (default `"development"`)
- Reads from environment variables; `.env` file support via `model_config`
- Exported as a module-level `settings` singleton

### `schema/health.py`
- `HealthResponse(BaseModel)` with fields:
  - `status: str` — always `"ok"`
  - `version: str` — from settings
  - `environment: str` — from settings

### `routes/health.py`
- `APIRouter` with prefix `/health`
- `GET /` → returns `HealthResponse`
- Depends on `settings` singleton from `app_config`

### `main.py`
- Creates `FastAPI` instance using `settings.app_name` as title and `settings.version` as version
- Includes the health router
- Exposes `app` for uvicorn

---

## Endpoint

| Method | Path      | Response Model  | Status |
|--------|-----------|-----------------|--------|
| GET    | /health   | HealthResponse  | 200 OK |

**Example response:**
```json
{
  "status": "ok",
  "version": "0.1.0",
  "environment": "development"
}
```

---

## Dependencies

- `fastapi` — web framework
- `uvicorn[standard]` — ASGI server
- `pydantic-settings` — settings management from env vars

Added to `pyproject.toml` via `uv add`.

---

## Running the Server

```bash
uv run uvicorn src.main:app --reload
```
