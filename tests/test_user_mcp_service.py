"""Tests for the user MCP server service."""

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from langchain_core.tools import BaseTool

from src.models.user_mcp_server import UserMcpServer
from src.schemas.user_mcp_server import (
    BearerAuthInput,
    HeaderAuthInput,
    UserMcpServerCreate,
    UserMcpServerImportRequest,
)
from src.services.user_mcp_service import (
    DuplicateMcpServerError,
    McpServerLimitError,
    UserMcpService,
    build_config_hash,
)
from src.utils.mcp_url import McpUrlError
from src.utils.secrets import decrypt_json

META_ADS_URL = "https://mcp-preview.strique.io/meta-ads/mcp"


class FakeResult:
    """Canned result for one `session.execute` call."""

    def __init__(self, value=None, values=None) -> None:
        """Store the scalar and list values this result should yield."""
        self.value = value
        self.values = values or []

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: self.values)


class FakeSession:
    """Async session double that replays canned query results in order."""

    def __init__(self, results=None) -> None:
        """Initialize the fake session with queued results."""
        self.results = list(results or [])
        self.added = []
        self.deleted = []
        self.commits = 0

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else FakeResult()

    def add(self, record) -> None:
        self.added.append(record)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _record) -> None:
        return None

    async def delete(self, record) -> None:
        self.deleted.append(record)


class FakeTool(BaseTool):
    """Minimal tool stand-in for discovery results."""

    name: str = "list_campaigns"
    description: str = "List ad campaigns."

    def _run(self, *args, **kwargs) -> str:
        return "ok"


class FakeMcpClient:
    """MultiServerMCPClient double that records the config it was built with."""

    last_config: dict = {}

    def __init__(self, connections: dict) -> None:
        """Record the connection config passed by the service."""
        FakeMcpClient.last_config = connections
        self.connections = connections

    async def get_tools(self, *, server_name: str):
        return [FakeTool(name="list_campaigns"), FakeTool(name="get_insights")]


class FailingMcpClient:
    """Client double whose connection always fails."""

    def __init__(self, connections: dict) -> None:
        """Accept and ignore the connection config."""
        self.connections = connections

    async def get_tools(self, *, server_name: str):
        raise ConnectionError("401 Unauthorized")


class TaskGroupFailingMcpClient:
    """Client double failing the way a real transport does: inside a task group."""

    def __init__(self, connections: dict) -> None:
        """Accept and ignore the connection config."""
        self.connections = connections

    async def get_tools(self, *, server_name: str):
        raise ExceptionGroup(
            "unhandled errors in a TaskGroup",
            [ConnectionError("Client error '401 Unauthorized' for url\n'https://mcp.example.com'")],
        )


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch) -> None:
    """Configure a throwaway encryption key for every test."""
    monkeypatch.setenv("RELIVO_MCP_SECRET_KEY", Fernet.generate_key().decode())


@pytest.fixture(autouse=True)
def no_dns(monkeypatch) -> None:
    """Skip DNS resolution so tests never touch the network."""

    async def fake_validate(url: str) -> list[str]:
        if not url.startswith("https://"):
            raise McpUrlError("https required")
        return ["203.0.113.10"]

    monkeypatch.setattr("src.services.user_mcp_service.validate_mcp_url", fake_validate)


def make_server(**overrides) -> UserMcpServer:
    """Build an unsaved server row with sensible defaults."""
    defaults = {
        "id": "server-1",
        "user_id": "user_1",
        "name": "meta-ads",
        "url": META_ADS_URL,
        "transport": "http",
        "auth_type": "header",
        "auth_header_names": ["x-api-key"],
        "allowed_tools": [],
        "timeout_seconds": 30.0,
        "sse_read_timeout_seconds": 300.0,
        "config_hash": "hash",
        "status": "pending",
        "tools": [],
        "tool_count": 0,
    }
    return UserMcpServer(**{**defaults, **overrides})


@pytest.mark.asyncio
async def test_create_server_encrypts_headers_and_stores_names() -> None:
    """Header values are encrypted; only the names stay in plaintext."""
    session = FakeSession([FakeResult(None), FakeResult(values=[])])
    service = UserMcpService(session)

    server = await service.create_server(
        "user_1",
        UserMcpServerCreate(
            name="meta-ads",
            url=META_ADS_URL,
            auth=HeaderAuthInput(headers={"x-api-key": "secret-value"}),
        ),
    )

    assert server.auth_type == "header"
    assert server.auth_header_names == ["x-api-key"]
    assert server.status == "pending"

    credential = next(record for record in session.added if hasattr(record, "headers_ciphertext"))
    assert "secret-value" not in credential.headers_ciphertext
    assert decrypt_json(credential.headers_ciphertext) == {"x-api-key": "secret-value"}


@pytest.mark.asyncio
async def test_create_server_from_pasted_json_end_to_end() -> None:
    """Raw pasted JSON reaches the database as a fully normalized row."""
    session = FakeSession([FakeResult(None), FakeResult(values=[])])
    service = UserMcpService(session)

    request = UserMcpServerImportRequest.model_validate(
        {"meta-ads": {"type": "http", "url": META_ADS_URL, "headers": {"x-api-key": "k"}}}
    )
    servers = await service.import_servers("user_1", request)

    assert len(servers) == 1
    assert servers[0].name == "meta-ads"
    assert servers[0].transport == "http"
    assert servers[0].auth_type == "header"
    assert servers[0].config_hash


@pytest.mark.asyncio
async def test_create_server_rejects_duplicate_name() -> None:
    """A second server with the same name for one user is refused."""
    session = FakeSession([FakeResult("existing-id")])
    service = UserMcpService(session)

    with pytest.raises(DuplicateMcpServerError):
        await service.create_server(
            "user_1", UserMcpServerCreate(name="meta-ads", url=META_ADS_URL)
        )


@pytest.mark.asyncio
async def test_create_server_enforces_the_per_user_limit(monkeypatch) -> None:
    """A user cannot register more servers than the configured cap."""
    monkeypatch.setenv("RELIVO_MCP_MAX_SERVERS", "2")
    session = FakeSession([FakeResult(None), FakeResult(values=["a", "b"])])
    service = UserMcpService(session)

    with pytest.raises(McpServerLimitError):
        await service.create_server("user_1", UserMcpServerCreate(name="third", url=META_ADS_URL))


@pytest.mark.asyncio
async def test_create_server_rejects_blocked_url() -> None:
    """The SSRF guard runs before anything is written."""
    session = FakeSession([FakeResult(None), FakeResult(values=[])])
    service = UserMcpService(session)

    with pytest.raises(McpUrlError):
        await service.create_server(
            "user_1",
            UserMcpServerCreate.model_construct(
                name="internal",
                url="http://169.254.169.254/mcp",
                transport="http",
                auth=HeaderAuthInput(headers={"x-api-key": "k"}),
                display_name=None,
                description=None,
                enabled=True,
                allowed_tools=[],
                timeout_seconds=30.0,
                sse_read_timeout_seconds=300.0,
            ),
        )
    assert session.added == []


def test_config_hash_changes_when_the_secret_rotates() -> None:
    """Rotating a key changes the hash, which is what invalidates the caches."""
    before = build_config_hash(META_ADS_URL, "http", HeaderAuthInput(headers={"x-api-key": "old"}))
    after = build_config_hash(META_ADS_URL, "http", HeaderAuthInput(headers={"x-api-key": "new"}))
    same = build_config_hash(META_ADS_URL, "http", HeaderAuthInput(headers={"x-api-key": "old"}))

    assert before != after
    assert before == same


def test_config_hash_changes_with_the_url() -> None:
    """A different URL is a different connection identity."""
    auth = HeaderAuthInput(headers={"x-api-key": "k"})
    assert build_config_hash(META_ADS_URL, "http", auth) != build_config_hash(
        "https://other.example.com/mcp", "http", auth
    )


@pytest.mark.asyncio
async def test_build_client_config_maps_http_to_streamable_http() -> None:
    """The stored transport is translated to the adapter's spelling."""
    session = FakeSession([FakeResult(None)])
    service = UserMcpService(session)
    server = make_server(auth_type="none", auth_header_names=[])

    config = await service.build_client_config(server)

    assert config["transport"] == "streamable_http"
    assert config["url"] == META_ADS_URL
    assert config["timeout"] == 30.0
    assert "headers" not in config


@pytest.mark.asyncio
async def test_build_client_config_sends_decrypted_headers() -> None:
    """Stored ciphertext is decrypted into the headers the server expects."""
    from src.utils.secrets import encrypt_json

    credential = SimpleNamespace(
        headers_ciphertext=encrypt_json({"x-api-key": "secret-value"}),
        oauth_access_token_ciphertext=None,
        oauth_token_type=None,
    )
    session = FakeSession([FakeResult(credential)])
    service = UserMcpService(session)

    config = await service.build_client_config(make_server())

    assert config["headers"] == {"x-api-key": "secret-value"}


@pytest.mark.asyncio
async def test_bearer_auth_is_sent_as_an_authorization_header() -> None:
    """A bearer token round-trips into the correct header."""
    session = FakeSession([FakeResult(None), FakeResult(values=[])])
    service = UserMcpService(session)

    server = await service.create_server(
        "user_1",
        UserMcpServerCreate(name="fc", url=META_ADS_URL, auth=BearerAuthInput(token="fc-123")),
    )
    credential = next(record for record in session.added if hasattr(record, "headers_ciphertext"))

    assert server.auth_header_names == ["Authorization"]
    assert decrypt_json(credential.headers_ciphertext) == {"Authorization": "Bearer fc-123"}


@pytest.mark.asyncio
async def test_test_server_records_discovered_tools(monkeypatch) -> None:
    """A successful connection stores the tool list and marks the server ready."""
    monkeypatch.setattr("src.services.user_mcp_service.MultiServerMCPClient", FakeMcpClient)
    server = make_server(auth_type="none", auth_header_names=[])
    session = FakeSession([FakeResult(server), FakeResult(None)])
    service = UserMcpService(session)

    result = await service.test_server("user_1", "server-1")

    assert result.status == "ready"
    assert result.tool_count == 2
    assert [tool.name for tool in result.tools] == [
        "mcp__meta-ads__list_campaigns",
        "mcp__meta-ads__get_insights",
    ]
    assert server.status == "ready"
    assert server.tool_count == 2
    assert server.last_connected_at is not None


@pytest.mark.asyncio
async def test_test_server_records_failures_without_raising(monkeypatch) -> None:
    """A dead server is reported in the body and recorded on the row."""
    monkeypatch.setattr("src.services.user_mcp_service.MultiServerMCPClient", FailingMcpClient)
    server = make_server(auth_type="none", auth_header_names=[])
    session = FakeSession([FakeResult(server), FakeResult(None)])
    service = UserMcpService(session)

    result = await service.test_server("user_1", "server-1")

    assert result.status == "unauthorized"
    assert "401" in result.error
    assert server.status == "unauthorized"
    assert server.last_error_at is not None


@pytest.mark.asyncio
async def test_test_server_unwraps_task_group_failures(monkeypatch) -> None:
    """The cause inside a task group is reported, not the group's own message."""
    monkeypatch.setattr(
        "src.services.user_mcp_service.MultiServerMCPClient", TaskGroupFailingMcpClient
    )
    server = make_server(auth_type="none", auth_header_names=[])
    session = FakeSession([FakeResult(server), FakeResult(None)])
    service = UserMcpService(session)

    result = await service.test_server("user_1", "server-1")

    assert "TaskGroup" not in result.error
    assert "401 Unauthorized" in result.error
    # Newlines are collapsed so the row stays one readable line in the UI.
    assert "\n" not in result.error
    assert result.status == "unauthorized"
    assert server.status_detail == result.error


@pytest.mark.asyncio
async def test_oauth_server_without_tokens_is_unauthorized(monkeypatch) -> None:
    """An OAuth server that never completed consent cannot connect."""
    monkeypatch.setattr("src.services.user_mcp_service.MultiServerMCPClient", FakeMcpClient)
    server = make_server(auth_type="oauth", auth_header_names=[], oauth_client_id="c_1")
    credential = SimpleNamespace(
        headers_ciphertext=None,
        oauth_access_token_ciphertext=None,
        oauth_token_type=None,
    )
    session = FakeSession([FakeResult(server), FakeResult(credential)])
    service = UserMcpService(session)

    result = await service.test_server("user_1", "server-1")

    assert result.status == "unauthorized"
    assert "OAuth" in result.error


@pytest.mark.asyncio
async def test_allowed_tools_filters_discovery(monkeypatch) -> None:
    """A tool filter is applied before the tools reach the agent."""
    monkeypatch.setattr("src.services.user_mcp_service.MultiServerMCPClient", FakeMcpClient)
    server = make_server(auth_type="none", auth_header_names=[], allowed_tools=["get_insights"])
    session = FakeSession([FakeResult(None)])
    service = UserMcpService(session)

    tools = await service.load_tools(server)

    assert [tool.name for tool in tools] == ["mcp__meta-ads__get_insights"]


@pytest.mark.asyncio
async def test_tool_count_is_capped(monkeypatch) -> None:
    """One chatty server cannot flood the prompt."""
    monkeypatch.setattr("src.services.user_mcp_service.MultiServerMCPClient", FakeMcpClient)
    monkeypatch.setenv("RELIVO_MCP_MAX_TOOLS", "1")
    server = make_server(auth_type="none", auth_header_names=[])
    session = FakeSession([FakeResult(None)])
    service = UserMcpService(session)

    assert len(await service.load_tools(server)) == 1
