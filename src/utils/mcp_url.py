"""SSRF guard for user-supplied remote MCP URLs."""

import asyncio
import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata",
        "metadata.google.internal",
    }
)


class McpUrlError(ValueError):
    """Raised when a user-supplied MCP URL fails validation."""


def allow_http() -> bool:
    """Return whether plain http URLs are permitted (local development only)."""
    return os.getenv("RELIVO_MCP_ALLOW_HTTP", "").strip().lower() in {"1", "true", "yes", "on"}


def is_blocked_ip(ip: str) -> bool:
    """Return whether an IP is in a range users must not be able to reach."""
    address = ipaddress.ip_address(ip)
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local  # 169.254.169.254 cloud metadata
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


async def validate_mcp_url(url: str) -> list[str]:
    """
    Validate a user MCP URL and return the resolved public IPs.

    Runs before any connection is opened. The returned IPs are the ones that
    passed validation; pinning the connection to them is what closes the
    DNS-rebinding window between this check and the request.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" and not (allow_http() and parsed.scheme == "http"):
        raise McpUrlError(f"scheme not allowed: {parsed.scheme or 'missing'} (https required)")

    host = parsed.hostname
    if not host:
        raise McpUrlError("url is missing a host")
    if host.lower() in BLOCKED_HOSTNAMES:
        raise McpUrlError(f"blocked host: {host}")

    ips = await resolve_host(host)
    if not ips:
        raise McpUrlError(f"could not resolve host: {host}")
    for ip in ips:
        if is_blocked_ip(ip):
            raise McpUrlError(f"blocked internal address {ip} for host {host}")
    return ips


async def resolve_host(host: str) -> list[str]:
    """Resolve a hostname to its IPs without blocking the event loop."""
    try:
        ipaddress.ip_address(host)
        return [host]
    except ValueError:
        pass

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise McpUrlError(f"could not resolve host: {host}") from exc
    return sorted({str(info[4][0]) for info in infos})
