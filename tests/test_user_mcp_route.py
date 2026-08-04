"""Tests for user MCP server routes."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from src.controllers.user_mcp_controller import get_user_mcp_service
from src.main import create_app
from src.schemas.user_mcp_server import UserMcpServerTestResponse
from src.services.user_mcp_service import DuplicateMcpServerError, UserMcpServerNotFoundError

META_ADS_URL = "https://mcp-preview.strique.io/meta-ads/mcp"


def fake_row(name: str, **overrides) -> SimpleNamespace:
    """Build a stored-server stand-in with every field the response reads."""
    now = datetime.now(UTC)
    defaults = {
        "id": f"{name}-id",
        "user_id": "user_1",
        "name": name,
        "display_name": None,
        "description": None,
        "url": META_ADS_URL,
        "transport": "http",
        "auth_type": "header",
        "auth_header_names": ["x-api-key"],
        "oauth_client_id": None,
        "oauth_registration": "manual",
        "oauth_scopes": [],
        "enabled": True,
        "status": "pending",
        "status_detail": None,
        "tools": [],
        "tool_count": 0,
        "allowed_tools": [],
        "timeout_seconds": 30.0,
        "sse_read_timeout_seconds": 300.0,
        "last_connected_at": None,
        "last_error_at": None,
        "created_at": now,
        "updated_at": now,
    }
    return SimpleNamespace(**{**defaults, **overrides})


class FakeService:
    """In-memory MCP service for route tests."""

    def __init__(self) -> None:
        """Initialize empty state and recorded calls."""
        self.created = []
        self.rows: dict[str, SimpleNamespace] = {}
        self.raise_duplicate = False
        self.test_result: UserMcpServerTestResponse | None = None

    async def list_servers(self, user_id: str) -> list[SimpleNamespace]:
        return list(self.rows.values())

    async def get_server(self, user_id: str, server_id: str) -> SimpleNamespace:
        if server_id not in self.rows:
            raise UserMcpServerNotFoundError(server_id)
        return self.rows[server_id]

    async def get_credential(self, server) -> None:
        return None

    async def create_server(self, user_id: str, payload) -> SimpleNamespace:
        if self.raise_duplicate:
            raise DuplicateMcpServerError(payload.name)
        self.created.append(payload)
        row = fake_row(payload.name, url=payload.url, transport=payload.transport)
        self.rows[row.id] = row
        return row

    async def import_servers(self, user_id: str, request) -> list[SimpleNamespace]:
        return [
            await self.create_server(user_id, entry.to_create(name))
            for name, entry in request.servers.items()
        ]

    async def update_server(self, user_id: str, server_id: str, payload) -> SimpleNamespace:
        return await self.get_server(user_id, server_id)

    async def delete_server(self, user_id: str, server_id: str) -> None:
        await self.get_server(user_id, server_id)
        self.rows.pop(server_id, None)

    async def test_server(self, user_id: str, server_id: str) -> UserMcpServerTestResponse:
        await self.get_server(user_id, server_id)
        return self.test_result


def build_client(service: FakeService) -> AsyncClient:
    """Build an HTTP client bound to the app with the fake service injected."""
    app = create_app()
    app.dependency_overrides[get_user_mcp_service] = lambda: service
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_import_accepts_a_bare_json_map() -> None:
    """Pasting the raw config with no wrapper is saved correctly."""
    service = FakeService()
    async with build_client(service) as client:
        response = await client.post(
            "/users/user_1/mcp-servers/import",
            json={"meta-ads": {"type": "http", "url": META_ADS_URL, "headers": {"x-api-key": "k"}}},
        )

    assert response.status_code == 201
    body = response.json()
    assert [server["name"] for server in body["servers"]] == ["meta-ads"]
    assert body["servers"][0]["auth"]["type"] == "header"
    assert body["servers"][0]["auth"]["header_names"] == ["x-api-key"]
    saved = service.created[0]
    assert saved.auth.type == "header"
    assert saved.auth.headers == {"x-api-key": "k"}


@pytest.mark.asyncio
async def test_import_accepts_the_mcp_servers_wrapper() -> None:
    """The standard config-file wrapper imports every entry."""
    service = FakeService()
    async with build_client(service) as client:
        response = await client.post(
            "/users/user_1/mcp-servers/import",
            json={
                "mcpServers": {
                    "meta-ads": {
                        "type": "http",
                        "url": META_ADS_URL,
                        "headers": {"x-api-key": "k"},
                    },
                    "deepwiki": {"type": "http", "url": "https://mcp.deepwiki.com/mcp"},
                }
            },
        )

    assert response.status_code == 201
    assert {server["name"] for server in response.json()["servers"]} == {"meta-ads", "deepwiki"}


@pytest.mark.asyncio
async def test_import_accepts_a_single_entry_and_derives_the_name() -> None:
    """A lone entry with no key gets a name derived from its URL."""
    service = FakeService()
    async with build_client(service) as client:
        response = await client.post(
            "/users/user_1/mcp-servers/import",
            json={"type": "http", "url": META_ADS_URL, "headers": {"x-api-key": "k"}},
        )

    assert response.status_code == 201
    assert response.json()["servers"][0]["name"] == "meta-ads"


@pytest.mark.asyncio
async def test_import_normalizes_a_bearer_header() -> None:
    """A pasted Authorization header is stored as bearer auth."""
    service = FakeService()
    async with build_client(service) as client:
        response = await client.post(
            "/users/user_1/mcp-servers/import",
            json={
                "fc": {
                    "url": "https://mcp.firecrawl.dev/v2/mcp",
                    "headers": {"Authorization": "Bearer fc-123"},
                }
            },
        )

    assert response.status_code == 201
    assert service.created[0].auth.type == "bearer"
    assert service.created[0].auth.token == "fc-123"


@pytest.mark.asyncio
async def test_import_rejects_stdio_config_with_a_clear_message() -> None:
    """A local server config explains why it cannot be used."""
    service = FakeService()
    async with build_client(service) as client:
        response = await client.post(
            "/users/user_1/mcp-servers/import",
            json={"mcpServers": {"local": {"command": "npx", "args": ["-y", "some-mcp"]}}},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["error_tag"] == "mcp_import_invalid"
    assert "stdio" in body["message"]


@pytest.mark.asyncio
async def test_create_rejects_insecure_url() -> None:
    """A plain http URL never reaches the service."""
    service = FakeService()
    async with build_client(service) as client:
        response = await client.post(
            "/users/user_1/mcp-servers",
            json={"name": "x", "url": "http://insecure.example.com/mcp"},
        )

    assert response.status_code == 422
    assert service.created == []


@pytest.mark.asyncio
async def test_create_duplicate_returns_conflict() -> None:
    """Registering the same name twice is a 409, not a 500."""
    service = FakeService()
    service.raise_duplicate = True
    async with build_client(service) as client:
        response = await client.post(
            "/users/user_1/mcp-servers",
            json={"name": "meta-ads", "url": META_ADS_URL},
        )

    assert response.status_code == 409
    assert response.json()["error_tag"] == "mcp_server_duplicate"


@pytest.mark.asyncio
async def test_list_servers() -> None:
    """Listing returns each registered server."""
    service = FakeService()
    row = fake_row("meta-ads")
    service.rows[row.id] = row
    async with build_client(service) as client:
        response = await client.get("/users/user_1/mcp-servers")

    assert response.status_code == 200
    assert [server["name"] for server in response.json()["servers"]] == ["meta-ads"]


@pytest.mark.asyncio
async def test_get_missing_server_returns_not_found() -> None:
    """An unknown server id is a 404 with the standard error body."""
    async with build_client(FakeService()) as client:
        response = await client.get("/users/user_1/mcp-servers/missing")

    assert response.status_code == 404
    assert response.json()["error_tag"] == "mcp_server_not_found"


@pytest.mark.asyncio
async def test_test_endpoint_reports_failure_in_the_body() -> None:
    """A failed connection is a 200 carrying the reason, not an error status."""
    service = FakeService()
    row = fake_row("meta-ads")
    service.rows[row.id] = row
    service.test_result = UserMcpServerTestResponse(
        server_id=row.id,
        status="error",
        error="connection refused",
    )
    async with build_client(service) as client:
        response = await client.post(f"/users/user_1/mcp-servers/{row.id}/test")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["error"] == "connection refused"


@pytest.mark.asyncio
async def test_delete_server() -> None:
    """Deleting removes the server."""
    service = FakeService()
    row = fake_row("meta-ads")
    service.rows[row.id] = row
    async with build_client(service) as client:
        response = await client.delete(f"/users/user_1/mcp-servers/{row.id}")

    assert response.status_code == 204
    assert service.rows == {}
