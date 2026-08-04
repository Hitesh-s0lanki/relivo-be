"""User MCP server HTTP controller."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db_session
from src.models.user_mcp_server import UserMcpServer
from src.schemas.user_mcp_server import (
    UserMcpServerCreate,
    UserMcpServerImportRequest,
    UserMcpServerListResponse,
    UserMcpServerResponse,
    UserMcpServerTestResponse,
    UserMcpServerUpdate,
    build_auth_summary,
)
from src.services.user_mcp_service import (
    DuplicateMcpServerError,
    McpServerLimitError,
    UserMcpServerNotFoundError,
    UserMcpService,
)
from src.utils.error_response import build_error_response
from src.utils.mcp_url import McpUrlError
from src.utils.secrets import SecretDecryptError, SecretKeyMissingError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users/{user_id}/mcp-servers", tags=["MCP Servers"])

UserIdPath = Annotated[str, Path(min_length=1, max_length=200)]
ServerIdPath = Annotated[str, Path(min_length=1, max_length=36)]


def get_user_mcp_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserMcpService:
    """Resolve the user MCP service dependency."""
    return UserMcpService(session)


UserMcpServiceDependency = Annotated[UserMcpService, Depends(get_user_mcp_service)]


@router.get("", response_model=UserMcpServerListResponse)
async def list_mcp_servers(
    user_id: UserIdPath,
    service: UserMcpServiceDependency,
) -> UserMcpServerListResponse:
    """List every MCP server a user has registered."""
    servers = await service.list_servers(user_id)
    return UserMcpServerListResponse(servers=[_to_response(server) for server in servers])


@router.post("", response_model=UserMcpServerResponse, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    user_id: UserIdPath,
    payload: UserMcpServerCreate,
    service: UserMcpServiceDependency,
) -> UserMcpServerResponse:
    """Register one remote MCP server."""
    with _translated_errors():
        server = await service.create_server(user_id, payload)
    return _to_response(server)


@router.post(
    "/import",
    response_model=UserMcpServerListResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_mcp_servers(
    user_id: UserIdPath,
    service: UserMcpServiceDependency,
    payload: Annotated[dict[str, Any], Body(...)],
) -> UserMcpServerListResponse:
    """
    Register servers from pasted MCP config JSON.

    The body is taken raw so every shape users actually paste is accepted:
    `{"servers": {...}}`, `{"mcpServers": {...}}`, a bare `{"name": {...}}` map,
    or a single `{"url": ...}` entry.
    """
    try:
        request = UserMcpServerImportRequest.model_validate(payload)
    except ValueError as exc:
        raise _http_error(400, _first_message(exc), "mcp_import_invalid") from exc

    with _translated_errors():
        servers = await service.import_servers(user_id, request)
    return UserMcpServerListResponse(servers=[_to_response(server) for server in servers])


@router.get("/{server_id}", response_model=UserMcpServerResponse)
async def get_mcp_server(
    user_id: UserIdPath,
    server_id: ServerIdPath,
    service: UserMcpServiceDependency,
) -> UserMcpServerResponse:
    """Read one registered MCP server."""
    with _translated_errors():
        server = await service.get_server(user_id, server_id)
        credential = await service.get_credential(server)
    return _to_response(server, credential)


@router.patch("/{server_id}", response_model=UserMcpServerResponse)
async def update_mcp_server(
    user_id: UserIdPath,
    server_id: ServerIdPath,
    payload: UserMcpServerUpdate,
    service: UserMcpServiceDependency,
) -> UserMcpServerResponse:
    """Update a registered MCP server."""
    with _translated_errors():
        server = await service.update_server(user_id, server_id, payload)
    return _to_response(server)


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    user_id: UserIdPath,
    server_id: ServerIdPath,
    service: UserMcpServiceDependency,
) -> None:
    """Delete a registered MCP server and its credentials."""
    with _translated_errors():
        await service.delete_server(user_id, server_id)


@router.post("/{server_id}/test", response_model=UserMcpServerTestResponse)
async def test_mcp_server(
    user_id: UserIdPath,
    server_id: ServerIdPath,
    service: UserMcpServiceDependency,
) -> UserMcpServerTestResponse:
    """
    Connect to a registered server and refresh its discovered tools.

    A failed connection is a successful call: the failure is recorded on the row
    and returned in the body, so the UI can show why without a 500.
    """
    with _translated_errors():
        return await service.test_server(user_id, server_id)


def _to_response(server: UserMcpServer, credential: Any = None) -> UserMcpServerResponse:
    """Build the API response for a server row."""
    return UserMcpServerResponse(
        id=server.id,
        user_id=server.user_id,
        name=server.name,
        display_name=server.display_name,
        description=server.description,
        url=server.url,
        transport=server.transport,
        auth=build_auth_summary(server, credential),
        enabled=server.enabled,
        status=server.status,
        status_detail=server.status_detail,
        tools=server.tools or [],
        tool_count=server.tool_count,
        allowed_tools=server.allowed_tools or [],
        timeout_seconds=server.timeout_seconds,
        sse_read_timeout_seconds=server.sse_read_timeout_seconds,
        last_connected_at=server.last_connected_at,
        last_error_at=server.last_error_at,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


class _translated_errors:  # noqa: N801 - context manager used like a decorator
    """Translate service errors into the standard API error shape."""

    def __enter__(self) -> "_translated_errors":
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        if exc is None:
            return False
        if isinstance(exc, UserMcpServerNotFoundError):
            raise _http_error(404, "mcp server not found", "mcp_server_not_found") from exc
        if isinstance(exc, DuplicateMcpServerError):
            raise _http_error(
                409,
                f"an mcp server named '{exc.args[0]}' already exists",
                "mcp_server_duplicate",
            ) from exc
        if isinstance(exc, McpServerLimitError):
            raise _http_error(
                409,
                f"maximum of {exc.args[0]} mcp servers reached",
                "mcp_server_limit",
            ) from exc
        if isinstance(exc, McpUrlError):
            raise _http_error(400, str(exc), "mcp_url_rejected") from exc
        if isinstance(exc, SecretKeyMissingError):
            raise _http_error(
                503,
                "credential encryption is not configured on this server",
                "mcp_secret_key_missing",
            ) from exc
        if isinstance(exc, SecretDecryptError):
            raise _http_error(
                500,
                "stored credential could not be decrypted",
                "mcp_secret_undecryptable",
            ) from exc
        return False


def _http_error(status_code: int, message: str, error_tag: str) -> HTTPException:
    """Build an HTTPException carrying the standard error body."""
    error = build_error_response(status=status_code, message=message, error_tag=error_tag)
    return HTTPException(status_code=status_code, detail=error.model_dump())


def _first_message(exc: Exception) -> str:
    """Return the most useful line of a validation error."""
    for line in str(exc).splitlines():
        stripped = line.strip()
        if stripped.startswith("Value error, "):
            return stripped[len("Value error, ") :]
    return "invalid mcp server configuration"
