"""User-registered remote MCP server database models."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.models.common import json_type, utc_now, uuid_str


class UserMcpServer(Base):
    """
    A remote (URL-based) MCP server registered by one user.

    Only non-secret configuration lives here. Every secret value (custom header
    values, OAuth client secret, OAuth tokens) is encrypted in
    :class:`UserMcpCredential` so list and read paths never load ciphertext.
    """

    __tablename__ = "user_mcp_servers"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_mcp_servers_user_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(String(200), index=True)

    # Slug used to namespace tools as `mcp__<name>__<tool>`; unique per user.
    name: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    url: Mapped[str] = mapped_column(String(2048))
    transport: Mapped[str] = mapped_column(String(20), default="http")

    auth_type: Mapped[str] = mapped_column(String(20), default="none")
    # Header names only, kept in plaintext so the UI can show what is configured.
    auth_header_names: Mapped[list[str]] = mapped_column(json_type, default=list)

    oauth_client_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    oauth_authorization_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    oauth_token_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    oauth_registration: Mapped[str] = mapped_column(String(20), default="manual")
    oauth_scopes: Mapped[list[str]] = mapped_column(json_type, default=list)
    # Cached RFC 9728 / RFC 8414 discovery documents.
    oauth_metadata: Mapped[dict[str, Any] | None] = mapped_column(json_type, nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Last successful tool discovery: [{"name": ..., "description": ...}, ...].
    tools: Mapped[list[dict[str, Any]]] = mapped_column(json_type, default=list)
    tool_count: Mapped[int] = mapped_column(Integer, default=0)
    # Empty list means "expose every tool the server advertises".
    allowed_tools: Mapped[list[str]] = mapped_column(json_type, default=list)

    timeout_seconds: Mapped[float] = mapped_column(Float, default=30.0)
    sse_read_timeout_seconds: Mapped[float] = mapped_column(Float, default=300.0)

    # sha256 over url + transport + auth material; changes on secret rotation so
    # the tool cache and the per-user agent graph invalidate automatically.
    config_hash: Mapped[str] = mapped_column(String(64), index=True)

    last_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    credential: Mapped["UserMcpCredential | None"] = relationship(
        back_populates="server",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        lazy="raise",
    )


class UserMcpCredential(Base):
    """Encrypted secrets for one registered MCP server."""

    __tablename__ = "user_mcp_credentials"
    __table_args__ = (UniqueConstraint("server_id", name="uq_user_mcp_credentials_server_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    server_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_mcp_servers.id", ondelete="CASCADE"),
    )
    user_id: Mapped[str] = mapped_column(String(200), index=True)

    # Identifies the encryption key used, so keys can be rotated in place.
    key_id: Mapped[str] = mapped_column(String(50), default="v1")

    # Encrypted JSON object of header name -> header value, e.g. {"x-api-key": "..."}.
    headers_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)

    oauth_client_secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_access_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_refresh_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_token_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    oauth_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    oauth_granted_scopes: Mapped[list[str]] = mapped_column(json_type, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    server: Mapped["UserMcpServer"] = relationship(back_populates="credential")
