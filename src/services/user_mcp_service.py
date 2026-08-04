"""Service for user-registered remote MCP servers."""

import hashlib
import logging
import os
import time
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.common import utc_now
from src.models.user_mcp_server import UserMcpCredential, UserMcpServer
from src.schemas.user_mcp_server import (
    McpAuthInput,
    McpToolSummary,
    UserMcpServerCreate,
    UserMcpServerImportRequest,
    UserMcpServerTestResponse,
    UserMcpServerUpdate,
)
from src.tools.mcp_registry import get_tool_registry
from src.utils.exception_detail import describe_exception
from src.utils.mcp_url import validate_mcp_url
from src.utils.secrets import decrypt_json, decrypt_text, encrypt_json, encrypt_text

logger = logging.getLogger(__name__)

DEFAULT_MAX_SERVERS_PER_USER = 20
DEFAULT_MAX_TOOLS_PER_SERVER = 64
TRANSPORT_TO_CLIENT = {"http": "streamable_http", "sse": "sse"}


class UserMcpServerNotFoundError(Exception):
    """Raised when a registered MCP server does not exist for the user."""


class DuplicateMcpServerError(Exception):
    """Raised when a user already registered a server under the same name."""


class McpServerLimitError(Exception):
    """Raised when a user exceeds their registered server allowance."""


class McpAuthUnavailableError(Exception):
    """Raised when a server's stored credentials are missing or unusable."""


class UserMcpService:
    """Create, read, update, and connection-test a user's remote MCP servers."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to a database session."""
        self.session = session

    async def list_servers(self, user_id: str) -> list[UserMcpServer]:
        """Return every server registered by one user, newest first."""
        result = await self.session.execute(
            select(UserMcpServer)
            .where(UserMcpServer.user_id == user_id)
            .order_by(UserMcpServer.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_server(self, user_id: str, server_id: str) -> UserMcpServer:
        """Return one server owned by the user."""
        result = await self.session.execute(
            select(UserMcpServer).where(
                UserMcpServer.id == server_id,
                UserMcpServer.user_id == user_id,
            )
        )
        server = result.scalar_one_or_none()
        if server is None:
            raise UserMcpServerNotFoundError(server_id)
        return server

    async def get_credential(self, server: UserMcpServer) -> UserMcpCredential | None:
        """Load the encrypted credential row for a server, if any."""
        result = await self.session.execute(
            select(UserMcpCredential).where(UserMcpCredential.server_id == server.id)
        )
        return result.scalar_one_or_none()

    async def create_server(
        self,
        user_id: str,
        payload: UserMcpServerCreate,
    ) -> UserMcpServer:
        """Register one remote MCP server for a user."""
        await self._assert_name_available(user_id, payload.name)
        await self._assert_within_limit(user_id)
        await validate_mcp_url(payload.url)

        server = UserMcpServer(
            user_id=user_id,
            name=payload.name,
            display_name=payload.display_name,
            description=payload.description,
            url=payload.url,
            transport=payload.transport,
            auth_type=payload.auth.type,
            auth_header_names=_header_names(payload.auth),
            enabled=payload.enabled,
            status="pending",
            allowed_tools=payload.allowed_tools,
            timeout_seconds=payload.timeout_seconds,
            sse_read_timeout_seconds=payload.sse_read_timeout_seconds,
            config_hash=build_config_hash(payload.url, payload.transport, payload.auth),
        )
        _apply_oauth_config(server, payload.auth)
        self.session.add(server)
        await self.session.flush()

        credential = _build_credential(server, payload.auth)
        if credential is not None:
            self.session.add(credential)
        await self.session.commit()
        await self.session.refresh(server)
        logger.info(
            "Registered MCP server user_id=%s name=%s auth=%s",
            user_id,
            server.name,
            server.auth_type,
        )
        return server

    async def import_servers(
        self,
        user_id: str,
        request: UserMcpServerImportRequest,
    ) -> list[UserMcpServer]:
        """
        Register every server in a pasted config block.

        Each entry is normalized into the same create path, so an import and a
        hand-written create produce identical rows.
        """
        created: list[UserMcpServer] = []
        for name, entry in request.servers.items():
            created.append(await self.create_server(user_id, entry.to_create(name)))
        return created

    async def update_server(
        self,
        user_id: str,
        server_id: str,
        payload: UserMcpServerUpdate,
    ) -> UserMcpServer:
        """Update a registered server. Omitting `auth` keeps stored credentials."""
        server = await self.get_server(user_id, server_id)
        previous_hash = server.config_hash
        fields = payload.model_dump(exclude_unset=True, exclude={"auth"})

        if payload.url is not None:
            await validate_mcp_url(payload.url)
        for key, value in fields.items():
            setattr(server, key, value)

        if payload.auth is not None:
            server.auth_type = payload.auth.type
            server.auth_header_names = _header_names(payload.auth)
            _apply_oauth_config(server, payload.auth)
            existing = await self.get_credential(server)
            if existing is not None:
                await self.session.delete(existing)
                await self.session.flush()
            credential = _build_credential(server, payload.auth)
            if credential is not None:
                self.session.add(credential)

        if payload.url is not None or payload.transport is not None or payload.auth is not None:
            auth = payload.auth
            if auth is None:
                # URL or transport changed without new credentials: keep the old
                # secret material in the hash by reusing the stored ciphertext.
                credential = await self.get_credential(server)
                secret_material = credential.headers_ciphertext if credential else ""
                server.config_hash = _hash_parts(
                    server.url, server.transport, server.auth_type, secret_material or ""
                )
            else:
                server.config_hash = build_config_hash(server.url, server.transport, auth)
            server.status = "pending"
            server.status_detail = None

        await self.session.commit()
        await self.session.refresh(server)
        # Drop the old tools immediately rather than serving a rotated-away
        # credential until the cache TTL expires.
        if server.config_hash != previous_hash:
            get_tool_registry().invalidate(previous_hash)
        return server

    async def delete_server(self, user_id: str, server_id: str) -> None:
        """Delete a server and its credentials."""
        server = await self.get_server(user_id, server_id)
        config_hash = server.config_hash
        credential = await self.get_credential(server)
        if credential is not None:
            await self.session.delete(credential)
        await self.session.delete(server)
        await self.session.commit()
        get_tool_registry().invalidate(config_hash)

    async def test_server(self, user_id: str, server_id: str) -> UserMcpServerTestResponse:
        """Connect to a server, refresh its discovered tools, and persist status."""
        server = await self.get_server(user_id, server_id)
        started = time.monotonic()

        try:
            tools = await self.load_tools(server)
        except Exception as exc:  # noqa: BLE001 - every failure is reported to the user
            detail = describe_exception(exc)[:1000]
            status = _status_for_error(exc, detail)
            server.status = status
            server.status_detail = detail
            server.last_error_at = utc_now()
            await self.session.commit()
            logger.warning("MCP connection test failed server=%s: %s", server.name, detail)
            return UserMcpServerTestResponse(
                server_id=server.id,
                status=status,
                error=detail,
            )

        summaries = [
            McpToolSummary(name=tool.name, description=(tool.description or None)) for tool in tools
        ]
        server.tools = [summary.model_dump() for summary in summaries]
        server.tool_count = len(summaries)
        server.status = "ready"
        server.status_detail = None
        server.last_connected_at = utc_now()
        await self.session.commit()

        return UserMcpServerTestResponse(
            server_id=server.id,
            status="ready",
            tools=summaries,
            tool_count=len(summaries),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    async def load_tools(self, server: UserMcpServer) -> list[BaseTool]:
        """Connect to one server and return its tools, namespaced per server."""
        config = await self.build_client_config(server)
        client = MultiServerMCPClient({server.name: config})
        tools = await client.get_tools(server_name=server.name)

        allowed = set(server.allowed_tools or [])
        if allowed:
            tools = [tool for tool in tools if tool.name in allowed]
        if len(tools) > max_tools_per_server():
            logger.warning(
                "Capping MCP tools server=%s %s -> %s",
                server.name,
                len(tools),
                max_tools_per_server(),
            )
            tools = tools[: max_tools_per_server()]
        return [_namespaced(server.name, tool) for tool in tools]

    async def build_client_config(self, server: UserMcpServer) -> dict[str, Any]:
        """Build the `MultiServerMCPClient` entry for a server, decrypting secrets."""
        await validate_mcp_url(server.url)

        config: dict[str, Any] = {
            "transport": TRANSPORT_TO_CLIENT[server.transport],
            "url": server.url,
            "timeout": server.timeout_seconds,
            "sse_read_timeout": server.sse_read_timeout_seconds,
        }
        headers = await self.resolve_headers(server)
        if headers:
            config["headers"] = headers
        return config

    async def resolve_headers(self, server: UserMcpServer) -> dict[str, str]:
        """Decrypt and return the headers to send to a server."""
        if server.auth_type == "none":
            return {}

        credential = await self.get_credential(server)
        if credential is None:
            raise McpAuthUnavailableError(f"no stored credentials for server '{server.name}'")

        if server.auth_type in {"bearer", "header"}:
            if not credential.headers_ciphertext:
                raise McpAuthUnavailableError(f"no stored headers for server '{server.name}'")
            return dict(decrypt_json(credential.headers_ciphertext))

        if not credential.oauth_access_token_ciphertext:
            raise McpAuthUnavailableError(
                f"server '{server.name}' has not completed its OAuth connection"
            )
        token = decrypt_text(credential.oauth_access_token_ciphertext)
        token_type = credential.oauth_token_type or "Bearer"
        return {"Authorization": f"{token_type} {token}"}

    async def _assert_name_available(self, user_id: str, name: str) -> None:
        result = await self.session.execute(
            select(UserMcpServer.id).where(
                UserMcpServer.user_id == user_id,
                UserMcpServer.name == name,
            )
        )
        if result.scalar_one_or_none() is not None:
            raise DuplicateMcpServerError(name)

    async def _assert_within_limit(self, user_id: str) -> None:
        result = await self.session.execute(
            select(UserMcpServer.id).where(UserMcpServer.user_id == user_id)
        )
        if len(list(result.scalars().all())) >= max_servers_per_user():
            raise McpServerLimitError(max_servers_per_user())


def max_servers_per_user() -> int:
    """Return the per-user registered server cap."""
    return int(os.getenv("RELIVO_MCP_MAX_SERVERS", DEFAULT_MAX_SERVERS_PER_USER))


def max_tools_per_server() -> int:
    """Return the per-server tool cap that protects the prompt budget."""
    return int(os.getenv("RELIVO_MCP_MAX_TOOLS", DEFAULT_MAX_TOOLS_PER_SERVER))


def build_config_hash(url: str, transport: str, auth: McpAuthInput) -> str:
    """
    Hash the connection identity, including secrets.

    Secrets are part of the hash on purpose: rotating a key changes the hash,
    which invalidates the tool cache and the cached agent graph with no
    explicit bust.
    """
    return _hash_parts(url, transport, auth.type, _auth_material(auth))


def _hash_parts(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _auth_material(auth: McpAuthInput) -> str:
    """Return the secret-bearing portion of an auth config for hashing."""
    if auth.type == "bearer":
        return auth.token
    if auth.type == "header":
        return "&".join(f"{key}={value}" for key, value in sorted(auth.headers.items()))
    if auth.type == "oauth":
        return f"{auth.client_id or ''}:{auth.client_secret or ''}"
    return ""


def _header_names(auth: McpAuthInput) -> list[str]:
    """Return the plaintext header names implied by an auth config."""
    if auth.type == "bearer":
        return ["Authorization"]
    if auth.type == "header":
        return list(auth.headers)
    return []


def _auth_headers(auth: McpAuthInput) -> dict[str, str]:
    """Return the header map to encrypt for an auth config."""
    if auth.type == "bearer":
        return {"Authorization": f"Bearer {auth.token}"}
    if auth.type == "header":
        return dict(auth.headers)
    return {}


def _apply_oauth_config(server: UserMcpServer, auth: McpAuthInput) -> None:
    """Copy non-secret OAuth fields onto the server row."""
    if auth.type != "oauth":
        server.oauth_client_id = None
        server.oauth_authorization_url = None
        server.oauth_token_url = None
        server.oauth_registration = "manual"
        server.oauth_scopes = []
        return
    server.oauth_client_id = auth.client_id
    server.oauth_authorization_url = auth.authorization_url
    server.oauth_token_url = auth.token_url
    server.oauth_registration = auth.registration
    server.oauth_scopes = list(auth.scopes)


def _build_credential(server: UserMcpServer, auth: McpAuthInput) -> UserMcpCredential | None:
    """Build the encrypted credential row for an auth config, if it has secrets."""
    headers = _auth_headers(auth)
    client_secret = auth.client_secret if auth.type == "oauth" else None
    if not headers and not client_secret:
        return None

    return UserMcpCredential(
        server_id=server.id,
        user_id=server.user_id,
        headers_ciphertext=encrypt_json(headers) if headers else None,
        oauth_client_secret_ciphertext=encrypt_text(client_secret) if client_secret else None,
    )


def _namespaced(server_name: str, tool: BaseTool) -> BaseTool:
    """Prefix a tool name so two servers cannot collide."""
    return tool.model_copy(update={"name": f"mcp__{server_name}__{tool.name}"})


def _status_for_error(exc: Exception, detail: str | None = None) -> str:
    """
    Map a connection failure onto a stored status.

    `detail` is the flattened description: the status of a task-group failure is
    only readable once the group has been unwrapped, since `str(exc)` on the
    group itself never mentions the 401 inside it.
    """
    message = (detail if detail is not None else str(exc)).lower()
    if (
        isinstance(exc, McpAuthUnavailableError)
        or "401" in message
        or "403" in message
        or "unauthorized" in message
        or "forbidden" in message
    ):
        return "unauthorized"
    return "error"
