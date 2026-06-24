"""Firecrawl MCP tools for the chat agent."""

import logging
import os
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)

DEFAULT_FIRECRAWL_MCP_URL = "https://mcp.firecrawl.dev/v2/mcp"
FIRECRAWL_MCP_SERVER_NAME = "firecrawl"
FIRECRAWL_API_KEY_PLACEHOLDERS = {"", "fc-your-key-here", "YOUR_API_KEY", "YOUR-API-KEY"}


async def load_firecrawl_mcp_tools() -> list[BaseTool]:
    """Load Firecrawl tools from its remote MCP server."""
    if not env_bool("FIRECRAWL_MCP_ENABLED", default=True):
        logger.info("Firecrawl MCP tools disabled by FIRECRAWL_MCP_ENABLED")
        return []

    url = firecrawl_mcp_url()
    if url == DEFAULT_FIRECRAWL_MCP_URL and not firecrawl_api_key():
        logger.info("Firecrawl MCP tools skipped because FIRECRAWL_API_KEY is not configured")
        return []

    client = MultiServerMCPClient(
        {
            FIRECRAWL_MCP_SERVER_NAME: {
                "transport": "http",
                "url": url,
                **firecrawl_mcp_auth_config(),
            }
        }
    )
    tools = await client.get_tools(server_name=FIRECRAWL_MCP_SERVER_NAME)
    logger.info("Loaded Firecrawl MCP tools count=%s", len(tools))
    return tools


def firecrawl_mcp_url() -> str:
    """Return the configured Firecrawl MCP URL."""
    url = os.getenv("FIRECRAWL_MCP_URL", DEFAULT_FIRECRAWL_MCP_URL).strip()
    api_key = firecrawl_api_key()
    if api_key and "{FIRECRAWL_API_KEY}" in url:
        return url.replace("{FIRECRAWL_API_KEY}", api_key)
    return url


def firecrawl_mcp_auth_config() -> dict[str, Any]:
    """Build optional Firecrawl MCP authentication config from environment."""
    api_key = firecrawl_api_key()
    if not api_key or "{FIRECRAWL_API_KEY}" in os.getenv("FIRECRAWL_MCP_URL", ""):
        return {}
    return {"headers": {"Authorization": f"Bearer {api_key}"}}


def firecrawl_api_key() -> str:
    """Return the configured Firecrawl API key when it is not a placeholder."""
    value = os.getenv("FIRECRAWL_API_KEY", "").strip()
    if value in FIRECRAWL_API_KEY_PLACEHOLDERS:
        return ""
    return value


def env_bool(name: str, *, default: bool) -> bool:
    """Read a boolean environment variable."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
