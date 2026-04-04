# FastAPI Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap a modular FastAPI server with a health check endpoint under `src/`, using Pydantic v2 models for response schemas and pydantic-settings for configuration.

**Architecture:** The app factory in `main.py` loads a singleton `Settings` from `app_config.py`, mounts an `APIRouter` from `routes/health.py`, and returns a `HealthResponse` Pydantic model defined in `schema/health.py`. All components are independently testable.

**Tech Stack:** Python 3.13, FastAPI, Uvicorn (standard), Pydantic v2, pydantic-settings, pytest, httpx (for test client)

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `pyproject.toml` | Add runtime + dev dependencies |
| Create | `src/__init__.py` | Mark `src` as package |
| Create | `src/app_config.py` | `Settings` singleton loaded from env |
| Create | `src/schema/__init__.py` | Mark `schema` as package |
| Create | `src/schema/health.py` | `HealthResponse` Pydantic model |
| Create | `src/routes/__init__.py` | Mark `routes` as package |
| Create | `src/routes/health.py` | `GET /health` route returning `HealthResponse` |
| Create | `src/main.py` | App factory — creates FastAPI, mounts routers |
| Create | `tests/__init__.py` | Mark `tests` as package |
| Create | `tests/test_health.py` | Integration test for `GET /health` |

---

### Task 1: Install Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add runtime dependencies**

```bash
uv add fastapi "uvicorn[standard]" pydantic-settings
```

Expected output includes lines like:
```
Added fastapi ...
Added uvicorn ...
Added pydantic-settings ...
```

- [ ] **Step 2: Add dev dependencies**

```bash
uv add --dev pytest httpx pytest-asyncio
```

Expected output includes lines like:
```
Added pytest ...
Added httpx ...
Added pytest-asyncio ...
```

- [ ] **Step 3: Verify pyproject.toml has dependencies**

```bash
cat pyproject.toml
```

Expected: `dependencies` array contains `fastapi`, `uvicorn[standard]`, `pydantic-settings`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add fastapi, uvicorn, pydantic-settings, pytest, httpx"
```

---

### Task 2: App Config

**Files:**
- Create: `src/__init__.py`
- Create: `src/app_config.py`

- [ ] **Step 1: Create src package**

Create `src/__init__.py` as an empty file.

```bash
mkdir -p src && touch src/__init__.py
```

- [ ] **Step 2: Write `src/app_config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "relivo-be-server"
    version: str = "0.1.0"
    environment: str = "development"


settings = Settings()
```

- [ ] **Step 3: Verify import works**

```bash
uv run python -c "from src.app_config import settings; print(settings.model_dump())"
```

Expected output:
```
{'app_name': 'relivo-be-server', 'version': '0.1.0', 'environment': 'development'}
```

- [ ] **Step 4: Commit**

```bash
git add src/__init__.py src/app_config.py
git commit -m "feat: add Settings config via pydantic-settings"
```

---

### Task 3: Health Response Schema

**Files:**
- Create: `src/schema/__init__.py`
- Create: `src/schema/health.py`
- Create: `tests/__init__.py`
- Create: `tests/test_health.py` (failing test first)

- [ ] **Step 1: Create schema package**

```bash
mkdir -p src/schema && touch src/schema/__init__.py
mkdir -p tests && touch tests/__init__.py
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_health.py`:

```python
from src.schema.health import HealthResponse


def test_health_response_shape():
    response = HealthResponse(status="ok", version="0.1.0", environment="development")
    assert response.status == "ok"
    assert response.version == "0.1.0"
    assert response.environment == "development"


def test_health_response_serializes_to_dict():
    response = HealthResponse(status="ok", version="0.1.0", environment="development")
    data = response.model_dump()
    assert data == {"status": "ok", "version": "0.1.0", "environment": "development"}
```

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest tests/test_health.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.schema.health'`

- [ ] **Step 4: Write `src/schema/health.py`**

```python
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/test_health.py -v
```

Expected:
```
tests/test_health.py::test_health_response_shape PASSED
tests/test_health.py::test_health_response_serializes_to_dict PASSED
2 passed
```

- [ ] **Step 6: Commit**

```bash
git add src/schema/__init__.py src/schema/health.py tests/__init__.py tests/test_health.py
git commit -m "feat: add HealthResponse schema with tests"
```

---

### Task 4: Health Route

**Files:**
- Create: `src/routes/__init__.py`
- Create: `src/routes/health.py`
- Modify: `tests/test_health.py`

- [ ] **Step 1: Create routes package**

```bash
mkdir -p src/routes && touch src/routes/__init__.py
```

- [ ] **Step 2: Write failing integration test — append to `tests/test_health.py`**

Add these imports and test at the bottom of `tests/test_health.py`:

```python
from fastapi.testclient import TestClient


def _make_client():
    from fastapi import FastAPI
    from src.routes.health import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_get_health_returns_200():
    client = _make_client()
    response = client.get("/health")
    assert response.status_code == 200


def test_get_health_response_body():
    client = _make_client()
    response = client.get("/health")
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "environment" in body
```

- [ ] **Step 3: Run test to verify new tests fail**

```bash
uv run pytest tests/test_health.py::test_get_health_returns_200 -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.routes.health'`

- [ ] **Step 4: Write `src/routes/health.py`**

```python
from fastapi import APIRouter
from src.app_config import settings
from src.schema.health import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
def get_health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.version,
        environment=settings.environment,
    )
```

- [ ] **Step 5: Run all health tests**

```bash
uv run pytest tests/test_health.py -v
```

Expected:
```
tests/test_health.py::test_health_response_shape PASSED
tests/test_health.py::test_health_response_serializes_to_dict PASSED
tests/test_health.py::test_get_health_returns_200 PASSED
tests/test_health.py::test_get_health_response_body PASSED
4 passed
```

- [ ] **Step 6: Commit**

```bash
git add src/routes/__init__.py src/routes/health.py tests/test_health.py
git commit -m "feat: add GET /health route with integration tests"
```

---

### Task 5: App Entry Point

**Files:**
- Create: `src/main.py`

- [ ] **Step 1: Write `src/main.py`**

```python
from fastapi import FastAPI
from src.app_config import settings
from src.routes.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
    )
    app.include_router(health_router)
    return app


app = create_app()
```

- [ ] **Step 2: Run all tests to confirm nothing broke**

```bash
uv run pytest tests/ -v
```

Expected: all 4 tests PASS.

- [ ] **Step 3: Smoke-test the running server**

```bash
uv run uvicorn src.main:app --reload &
sleep 2
curl -s http://localhost:8000/health | python -m json.tool
kill %1
```

Expected:
```json
{
    "status": "ok",
    "version": "0.1.0",
    "environment": "development"
}
```

- [ ] **Step 4: Commit**

```bash
git add src/main.py
git commit -m "feat: add FastAPI app entry point"
```

---

## Running the Server

```bash
uv run uvicorn src.main:app --reload
```

- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health
