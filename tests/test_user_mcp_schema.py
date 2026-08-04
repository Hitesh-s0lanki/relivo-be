"""Tests for parsing pasted MCP server JSON."""

import pytest

from src.schemas.user_mcp_server import (
    UserMcpServerCreate,
    UserMcpServerImportRequest,
    derive_server_name,
    slugify_server_name,
)

META_ADS_URL = "https://mcp-preview.strique.io/meta-ads/mcp"


def first_create(payload: dict) -> UserMcpServerCreate:
    """Normalize a raw payload down to its single create request."""
    request = UserMcpServerImportRequest.model_validate(payload)
    name = next(iter(request.servers))
    return request.servers[name].to_create(name)


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("servers wrapper", {"servers": {"meta-ads": {"type": "http", "url": META_ADS_URL}}}),
        ("mcpServers wrapper", {"mcpServers": {"meta-ads": {"type": "http", "url": META_ADS_URL}}}),
        ("bare map", {"meta-ads": {"type": "http", "url": META_ADS_URL}}),
        ("single entry", {"type": "http", "url": META_ADS_URL}),
        ("url only", {"url": META_ADS_URL}),
    ],
)
def test_every_paste_shape_normalizes_to_the_same_server(label: str, payload: dict) -> None:
    """Each shape a user might paste produces the same normalized create."""
    create = first_create(payload)
    assert create.name == "meta-ads", label
    assert create.url == META_ADS_URL
    assert create.transport == "http"


def test_headers_become_header_auth() -> None:
    """A pasted headers map is stored as header auth."""
    create = first_create(
        {"meta-ads": {"type": "http", "url": META_ADS_URL, "headers": {"x-api-key": "secret"}}}
    )
    assert create.auth.type == "header"
    assert create.auth.headers == {"x-api-key": "secret"}


def test_multiple_headers_are_preserved() -> None:
    """Every header in a pasted map survives normalization."""
    create = first_create(
        {
            "analytics": {
                "url": "https://mcp.example.com/mcp",
                "headers": {"x-api-key": "k", "x-workspace-id": "ws", "x-env": "prod"},
            }
        }
    )
    assert create.auth.headers == {"x-api-key": "k", "x-workspace-id": "ws", "x-env": "prod"}


def test_lone_authorization_bearer_becomes_bearer_auth() -> None:
    """`Authorization: Bearer x` is normalized to bearer auth, not a raw header."""
    create = first_create(
        {
            "fc": {
                "url": "https://mcp.firecrawl.dev/v2/mcp",
                "headers": {"Authorization": "Bearer fc-123"},
            }
        }
    )
    assert create.auth.type == "bearer"
    assert create.auth.token == "fc-123"


def test_authorization_alongside_other_headers_stays_header_auth() -> None:
    """A bearer header mixed with others is kept verbatim as header auth."""
    create = first_create(
        {
            "svc": {
                "url": "https://mcp.example.com/mcp",
                "headers": {"Authorization": "Bearer t", "x-tenant": "acme"},
            }
        }
    )
    assert create.auth.type == "header"
    assert create.auth.headers["Authorization"] == "Bearer t"


def test_no_headers_becomes_no_auth() -> None:
    """An entry without headers is stored as unauthenticated."""
    assert first_create({"deepwiki": {"url": "https://mcp.deepwiki.com/mcp"}}).auth.type == "none"


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [
        ("http", "http"),
        ("streamable-http", "http"),
        ("streamable_http", "http"),
        ("sse", "sse"),
    ],
)
def test_transport_spellings(spelling: str, expected: str) -> None:
    """Every transport spelling in the wild maps onto a supported transport."""
    assert first_create({"a": {"type": spelling, "url": META_ADS_URL}}).transport == expected


def test_langchain_style_transport_key_is_honoured() -> None:
    """`transport` is read when `type` is absent, so sse is not silently http."""
    create = first_create({"a": {"transport": "sse", "url": "https://mcp.example.com/sse"}})
    assert create.transport == "sse"


def test_unknown_keys_are_ignored() -> None:
    """A block copied from another client does not need trimming first."""
    create = first_create(
        {"a": {"type": "http", "url": META_ADS_URL, "disabled": False, "note": "hi", "env": {}}}
    )
    assert create.url == META_ADS_URL


def test_names_are_slugified() -> None:
    """Keys that are not valid slugs are coerced rather than rejected."""
    request = UserMcpServerImportRequest.model_validate(
        {"servers": {"Meta Ads": {"url": META_ADS_URL}}}
    )
    assert list(request.servers) == ["meta-ads"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"servers": {"local": {"command": "npx", "args": ["-y", "x"]}}}, "stdio"),
        ({"servers": {"local": {"type": "stdio", "url": META_ADS_URL}}}, "stdio"),
        ({"servers": {"ws": {"type": "websocket", "url": META_ADS_URL}}}, "unsupported transport"),
        ({"url": "http://insecure.example.com/mcp"}, "https"),
        ({"url": "https://mcp.example.com/mcp#frag"}, "fragment"),
    ],
)
def test_rejected_payloads(payload: dict, message: str) -> None:
    """Unsupported entries fail with an explanation, not a generic error."""
    with pytest.raises(ValueError, match=message):
        first_create(payload)


def test_duplicate_names_after_slugification_are_rejected() -> None:
    """Two keys that collide once slugified cannot both be imported."""
    with pytest.raises(ValueError, match="duplicate server name"):
        UserMcpServerImportRequest.model_validate(
            {
                "servers": {
                    "Meta Ads": {"url": "https://a.example.com/mcp"},
                    "meta-ads": {"url": "https://b.example.com/mcp"},
                }
            }
        )


def test_reserved_headers_are_rejected() -> None:
    """A header the transport owns cannot be set by a user."""
    with pytest.raises(ValueError, match="reserved"):
        first_create({"a": {"url": META_ADS_URL, "headers": {"Host": "evil.example.com"}}})


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://mcp-preview.strique.io/meta-ads/mcp", "meta-ads"),
        ("https://mcp.notion.com/mcp", "notion"),
        ("https://mcp.firecrawl.dev/v2/mcp", "firecrawl"),
        ("https://mcp.deepwiki.com/mcp", "deepwiki"),
    ],
)
def test_derive_server_name(url: str, expected: str) -> None:
    """A name is derived from the URL when the payload carries no key."""
    assert derive_server_name(url) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Meta Ads", "meta-ads"),
        ("meta.ads.v2", "meta-ads-v2"),
        ("  Spaced  Name  ", "spaced-name"),
        ("UPPER_CASE", "upper_case"),
    ],
)
def test_slugify_server_name(raw: str, expected: str) -> None:
    """Server keys are coerced into tool-name-safe slugs."""
    assert slugify_server_name(raw) == expected
