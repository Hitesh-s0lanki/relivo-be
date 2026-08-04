"""Schemas for user-registered remote MCP server APIs."""

import re
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

McpTransport = Literal["http", "sse"]
McpAuthType = Literal["none", "bearer", "header", "oauth"]
McpServerStatus = Literal["pending", "ready", "error", "unauthorized"]
McpOAuthRegistration = Literal["manual", "dynamic"]

SERVER_NAME_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
HEADER_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9\-_]{0,127}$"

# Headers the transport owns. Letting a user set these breaks the connection or
# smuggles the request somewhere else, so they are rejected at the API boundary.
RESERVED_HEADER_NAMES = frozenset(
    {
        "host",
        "content-length",
        "content-type",
        "connection",
        "keep-alive",
        "transfer-encoding",
        "upgrade",
        "te",
        "trailer",
        "proxy-authorization",
        "proxy-authenticate",
        "expect",
        "accept",
        "mcp-session-id",
        "mcp-protocol-version",
    }
)

MAX_HEADERS = 10
MAX_HEADER_VALUE_LENGTH = 4096


class NoAuthInput(BaseModel):
    """No authentication; the MCP server is public."""

    type: Literal["none"] = "none"


class BearerAuthInput(BaseModel):
    """Static bearer token sent as `Authorization: Bearer <token>`."""

    type: Literal["bearer"] = "bearer"
    token: str = Field(..., min_length=1, max_length=MAX_HEADER_VALUE_LENGTH)


class HeaderAuthInput(BaseModel):
    """One or more custom headers, e.g. `{"x-api-key": "..."}`."""

    type: Literal["header"] = "header"
    headers: dict[str, str] = Field(..., min_length=1, max_length=MAX_HEADERS)

    @field_validator("headers")
    @classmethod
    def validate_headers(cls, value: dict[str, str]) -> dict[str, str]:
        """Reject reserved, malformed, or oversized headers."""
        seen: set[str] = set()
        for name, header_value in value.items():
            lowered = name.strip().lower()
            if lowered in RESERVED_HEADER_NAMES:
                raise ValueError(f"header '{name}' is reserved by the transport")
            if lowered in seen:
                raise ValueError(f"duplicate header '{name}'")
            if not _matches(HEADER_NAME_PATTERN, name.strip()):
                raise ValueError(f"invalid header name '{name}'")
            if not header_value.strip():
                raise ValueError(f"header '{name}' has an empty value")
            if len(header_value) > MAX_HEADER_VALUE_LENGTH:
                raise ValueError(f"header '{name}' value is too long")
            seen.add(lowered)
        return {name.strip(): header_value.strip() for name, header_value in value.items()}


class OAuthAuthInput(BaseModel):
    """
    OAuth 2.1 client credentials for a protected MCP server.

    `authorization_url` and `token_url` are optional: when omitted they are
    discovered from the server's protected resource metadata (RFC 9728) and the
    authorization server metadata (RFC 8414 / OIDC Discovery). With
    `registration="dynamic"` the client is registered on the fly (RFC 7591) and
    `client_id` may also be omitted.
    """

    type: Literal["oauth"] = "oauth"
    client_id: str | None = Field(default=None, max_length=500)
    client_secret: str | None = Field(default=None, max_length=MAX_HEADER_VALUE_LENGTH)
    authorization_url: str | None = Field(default=None, max_length=2048)
    token_url: str | None = Field(default=None, max_length=2048)
    registration: McpOAuthRegistration = "manual"
    scopes: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_registration(self) -> "OAuthAuthInput":
        """Require a client id unless the client is registered dynamically."""
        if self.registration == "manual" and not self.client_id:
            raise ValueError("client_id is required when registration is 'manual'")
        return self


McpAuthInput = Annotated[
    NoAuthInput | BearerAuthInput | HeaderAuthInput | OAuthAuthInput,
    Field(discriminator="type"),
]


class UserMcpServerCreate(BaseModel):
    """Request body for registering a remote MCP server."""

    name: str = Field(..., pattern=SERVER_NAME_PATTERN)
    display_name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    url: str = Field(..., min_length=1, max_length=2048)
    transport: McpTransport = "http"
    auth: McpAuthInput = Field(default_factory=NoAuthInput)
    enabled: bool = True
    allowed_tools: list[str] = Field(default_factory=list, max_length=200)
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    sse_read_timeout_seconds: float = Field(default=300.0, gt=0, le=1800)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Require an absolute https URL with no fragment."""
        return normalize_mcp_url(value)


class UserMcpServerUpdate(BaseModel):
    """
    Request body for updating a registered MCP server.

    Omitting `auth` leaves the stored credentials untouched; sending it replaces
    them wholesale.
    """

    display_name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    transport: McpTransport | None = None
    auth: McpAuthInput | None = None
    enabled: bool | None = None
    allowed_tools: list[str] | None = Field(default=None, max_length=200)
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    sse_read_timeout_seconds: float | None = Field(default=None, gt=0, le=1800)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        """Require an absolute https URL with no fragment when a URL is sent."""
        return None if value is None else normalize_mcp_url(value)


class McpServerImport(BaseModel):
    """
    A single entry from a pasted MCP config block.

    Accepts the shapes users already have on hand. `type` (VS Code, Claude) and
    `transport` (`langchain-mcp-adapters`) are both honoured, along with the
    `streamable-http` / `streamable_http` spellings::

        {"type": "http", "url": "https://mcp.example.com/mcp", "headers": {"x-api-key": "..."}}
        {"transport": "streamable_http", "url": "https://mcp.example.com/mcp"}
    """

    model_config = ConfigDict(extra="ignore")

    transport: McpTransport = "http"
    url: str = Field(..., min_length=1, max_length=2048)
    headers: dict[str, str] = Field(default_factory=dict, max_length=MAX_HEADERS)
    name: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def normalize_entry(cls, value: Any) -> Any:
        """Fold `type`/`transport` spellings together and reject stdio entries."""
        if not isinstance(value, dict):
            return value

        entry = dict(value)
        if "command" in entry or "args" in entry:
            raise ValueError(
                "local (stdio) MCP servers are not supported; provide a remote https url"
            )

        raw = entry.pop("type", None) or entry.get("transport") or "http"
        transport = str(raw).strip().lower().replace("_", "-")
        if transport == "stdio":
            raise ValueError(
                "local (stdio) MCP servers are not supported; provide a remote https url"
            )
        if transport in {"http", "https", "streamable-http", "streamablehttp"}:
            entry["transport"] = "http"
        elif transport == "sse":
            entry["transport"] = "sse"
        else:
            raise ValueError(f"unsupported transport '{raw}'")
        return entry

    def to_create(self, name: str) -> UserMcpServerCreate:
        """Normalize this entry into a create request."""
        return UserMcpServerCreate(
            name=name,
            display_name=self.display_name,
            description=self.description,
            url=self.url,
            transport=self.transport,
            auth=_auth_from_headers(self.headers),
        )


class UserMcpServerImportRequest(BaseModel):
    """
    Request body for importing pasted MCP config JSON.

    The canonical form is `{"servers": {...}}`, but the raw shapes users
    actually paste are normalized into it first:

    - `{"mcpServers": {...}}` — the standard config file wrapper
    - `{"meta-ads": {...}}` — a bare server map with no wrapper
    - `{"type": "http", "url": "..."}` — a single entry, name derived from the URL
    """

    servers: dict[str, McpServerImport] = Field(..., min_length=1, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, value: Any) -> Any:
        """Accept every raw paste shape and reduce it to `{"servers": {...}}`."""
        if not isinstance(value, dict):
            return value

        for wrapper in ("servers", "mcpServers", "mcp_servers"):
            inner = value.get(wrapper)
            if isinstance(inner, dict):
                return {"servers": _keyed_by_slug(inner)}

        # A single bare entry, e.g. what the "Add MCP by URL" dialog submits.
        if any(key in value for key in ("url", "type", "transport", "command", "args")):
            name = value.get("name") or derive_server_name(str(value.get("url", "")))
            return {"servers": _keyed_by_slug({name: value})}

        # Otherwise treat the whole object as the server map itself.
        if value and all(isinstance(entry, dict) for entry in value.values()):
            return {"servers": _keyed_by_slug(value)}
        return value


class McpAuthSummary(BaseModel):
    """Non-secret view of a server's auth configuration."""

    type: McpAuthType
    configured: bool = False
    header_names: list[str] = Field(default_factory=list)
    oauth_client_id: str | None = None
    oauth_registration: McpOAuthRegistration | None = None
    scopes: list[str] = Field(default_factory=list)
    token_expires_at: datetime | None = None


class McpToolSummary(BaseModel):
    """One tool advertised by a registered MCP server."""

    name: str
    description: str | None = None


class UserMcpServerResponse(BaseModel):
    """Registered MCP server response body. Never contains secret values."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    display_name: str | None
    description: str | None
    url: str
    transport: McpTransport
    auth: McpAuthSummary
    enabled: bool
    status: McpServerStatus
    status_detail: str | None
    tools: list[McpToolSummary]
    tool_count: int
    allowed_tools: list[str]
    timeout_seconds: float
    sse_read_timeout_seconds: float
    last_connected_at: datetime | None
    last_error_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserMcpServerListResponse(BaseModel):
    """List of a user's registered MCP servers."""

    servers: list[UserMcpServerResponse]


class UserMcpServerTestResponse(BaseModel):
    """Result of a connection test against a registered MCP server."""

    server_id: str
    status: McpServerStatus
    tools: list[McpToolSummary] = Field(default_factory=list)
    tool_count: int = 0
    latency_ms: int | None = None
    error: str | None = None


class McpOAuthStartResponse(BaseModel):
    """Authorization URL the frontend must open to complete an OAuth connection."""

    server_id: str
    authorization_url: str
    state: str
    expires_in_seconds: int = Field(..., ge=1)


class McpOAuthCallbackRequest(BaseModel):
    """Authorization code returned to the OAuth redirect URI."""

    state: str = Field(..., min_length=1, max_length=500)
    code: str | None = Field(default=None, max_length=2048)
    error: str | None = Field(default=None, max_length=500)
    error_description: str | None = Field(default=None, max_length=2000)
    iss: str | None = Field(default=None, max_length=2048)


def normalize_mcp_url(value: str) -> str:
    """
    Validate and canonicalize a user-supplied MCP server URL.

    Shape only. The SSRF guard (DNS resolution plus private/link-local IP
    rejection) runs in the service layer before any connection is made.
    """
    url = value.strip()
    if not url.startswith("https://"):
        raise ValueError("url must be an absolute https:// URL")
    if "#" in url:
        raise ValueError("url must not contain a fragment")
    if len(url) <= len("https://"):
        raise ValueError("url is missing a host")
    return url.rstrip("/") or url


def slugify_server_name(value: str) -> str:
    """
    Coerce a pasted server key into a valid slug.

    Config files in the wild use keys like `Meta Ads` or `meta.ads`, which cannot
    be used verbatim because the name becomes part of a tool name.
    """
    slug = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-_")
    slug = re.sub(r"-{2,}", "-", slug)[:64].strip("-_")
    if not slug or not slug[0].isalnum():
        slug = f"mcp-{slug}".strip("-_")[:64]
    if not _matches(SERVER_NAME_PATTERN, slug):
        raise ValueError(f"cannot derive a valid server name from '{value}'")
    return slug


def derive_server_name(url: str) -> str:
    """
    Derive a server name from its URL when the payload carries no key.

    `https://mcp-preview.strique.io/meta-ads/mcp` yields `meta-ads`;
    `https://mcp.notion.com/mcp` falls back to the host and yields `notion`.
    """
    parsed = urlparse(url.strip())
    ignored = {"mcp", "sse", "api", "v1", "v2", "v3", "server"}

    for segment in reversed([part for part in parsed.path.split("/") if part]):
        if segment.lower() not in ignored:
            return slugify_server_name(segment)

    labels = [label for label in (parsed.hostname or "").split(".") if label]
    for label in labels[:-1] if len(labels) > 1 else labels:
        if label.lower() not in ignored and label.lower() != "www":
            return slugify_server_name(label)
    raise ValueError("could not derive a server name from the url; send an explicit name")


def _keyed_by_slug(mapping: dict[str, Any]) -> dict[str, Any]:
    """Slugify every key, rejecting entries that collide after slugification."""
    result: dict[str, Any] = {}
    for key, entry in mapping.items():
        slug = slugify_server_name(str(key))
        if slug in result:
            raise ValueError(f"duplicate server name '{slug}' after normalization")
        result[slug] = entry
    return result


def _auth_from_headers(headers: dict[str, str]) -> "McpAuthInput":
    """
    Pick the auth type implied by a pasted `headers` map.

    A lone `Authorization: Bearer <token>` is stored as `bearer` rather than a
    raw header so the UI renders a token field and rotation stays one input.
    """
    if not headers:
        return NoAuthInput()
    if len(headers) == 1:
        name, value = next(iter(headers.items()))
        if name.strip().lower() == "authorization" and value.strip().lower().startswith("bearer "):
            return BearerAuthInput(token=value.strip()[len("bearer ") :].strip())
    return HeaderAuthInput(headers=headers)


def _matches(pattern: str, value: str) -> bool:
    """Return whether a value fully matches a pattern."""
    return re.fullmatch(pattern, value) is not None


def build_auth_summary(server: Any, credential: Any = None) -> McpAuthSummary:
    """
    Build the non-secret auth summary for a `UserMcpServer` row.

    The credential row is passed in rather than read off the relationship, which
    is `lazy="raise"` so list endpoints never load ciphertext by accident. Pass
    it only where the caller already loaded it.
    """
    if server.auth_type == "oauth":
        return McpAuthSummary(
            type="oauth",
            configured=bool(credential and credential.oauth_access_token_ciphertext),
            oauth_client_id=server.oauth_client_id,
            oauth_registration=server.oauth_registration,
            scopes=list(server.oauth_scopes or []),
            token_expires_at=getattr(credential, "oauth_expires_at", None),
        )
    header_names = list(server.auth_header_names or [])
    return McpAuthSummary(
        type=server.auth_type,
        configured=bool(header_names),
        header_names=header_names,
    )
