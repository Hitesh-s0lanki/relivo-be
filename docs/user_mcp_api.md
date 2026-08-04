# Custom MCP Server API

> **Status: implemented, except OAuth.** Tables, models, schemas, service, routes, and the
> per-user agent wiring exist and are covered by tests (`tests/test_user_mcp_schema.py`,
> `tests/test_user_mcp_service.py`, `tests/test_user_mcp_route.py`,
> `tests/test_mcp_registry.py`, `tests/test_agent_resolution.py`,
> `tests/test_chat_agent_resolution.py`).
>
> **Not implemented:** the two OAuth endpoints (`/oauth/start`, `/oauth/callback`) — an OAuth
> server can be registered and stores its client credentials, but reports `unauthorized` until
> tokens exist.
>
> Set `RELIVO_MCP_SECRET_KEY` before registering any server that carries a secret. Without it,
> writes that need encryption fail with a 503 rather than storing plaintext.

A user registers a **remote MCP server by URL**. From then on, that server's tools are bound
into *their* agent only. Local/stdio servers are explicitly out of scope — nothing is spawned
on our machines, so the only transports are `http` (Streamable HTTP) and `sse`.

## Auth model

The UI's advanced panel is not OAuth-only. Real servers authenticate in several ways, and a
single `auth` object with a `type` discriminator covers all of them:

| `auth.type` | What the user supplies | What we send |
|-------------|------------------------|--------------|
| `none` | nothing | no auth header |
| `bearer` | one token | `Authorization: Bearer <token>` |
| `header` | a map of header name → value | those headers verbatim |
| `oauth` | client id + secret (+ optional URLs, scopes) | `Authorization: Bearer <access_token>`, refreshed automatically |

`bearer` is technically a special case of `header`, but keeping it separate lets the UI render
a single "Token" field instead of a key/value grid, which is what most servers need.

The sample config maps onto `header` auth:

```json
"meta-ads": {
  "type": "http",
  "url": "https://mcp-preview.strique.io/meta-ads/mcp",
  "headers": { "x-api-key": "chnXDPDKtMC7Faoprk6u8euLK" }
}
```

becomes

```json
{
  "name": "meta-ads",
  "url": "https://mcp-preview.strique.io/meta-ads/mcp",
  "transport": "http",
  "auth": { "type": "header", "headers": { "x-api-key": "chnXDPDKtMC7Faoprk6u8euLK" } }
}
```

`POST /users/{user_id}/mcp-servers/import` accepts the first form directly, so a user can paste
the `mcpServers` block they already have.

## Data model

Two tables. Non-secret config is separated from ciphertext so list and read paths never load a
secret, and so key rotation touches one narrow table.

### `user_mcp_servers`

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | UUID. Primary key. |
| `user_id` | string | Clerk user id. Joins to `users.id`. |
| `name` | string | Slug, unique per user, `^[a-z0-9][a-z0-9_-]{0,63}$`. Namespaces tools as `mcp__<name>__<tool>`. |
| `display_name` | string/null | Label shown in the UI. |
| `description` | string/null | User's own note about the server. |
| `url` | string | Absolute `https://` URL, no fragment. |
| `transport` | string | `http` (Streamable HTTP) or `sse`. |
| `auth_type` | string | `none`, `bearer`, `header`, `oauth`. |
| `auth_header_names` | array | Header **names** only, plaintext, so the UI can show what is configured without decrypting. |
| `oauth_client_id` | string/null | Not secret; shown back to the user. |
| `oauth_authorization_url` | string/null | Null when discovered per RFC 9728 / RFC 8414. |
| `oauth_token_url` | string/null | Same. |
| `oauth_registration` | string | `manual` (user pasted a client id) or `dynamic` (RFC 7591). |
| `oauth_scopes` | array | Requested scopes. |
| `oauth_metadata` | object/null | Cached discovery documents. |
| `enabled` | boolean | Disabled servers are skipped at tool-load time. |
| `status` | string | `pending`, `ready`, `error`, `unauthorized`. |
| `status_detail` | string/null | Last error message, shown in the UI. |
| `tools` | array | Last successful discovery: `[{"name", "description"}]`. Lets the UI list tools without a live connection. |
| `tool_count` | integer | Length of `tools` at last discovery. |
| `allowed_tools` | array | Tool filter. Empty means all. |
| `timeout_seconds` | float | Request timeout. Default 30. |
| `sse_read_timeout_seconds` | float | SSE read timeout. Default 300. |
| `config_hash` | string | sha256 over url + transport + auth material. |
| `last_connected_at` | datetime/null | Last successful connection. |
| `last_error_at` | datetime/null | Last failure. |
| `created_at` / `updated_at` | datetime | Row timestamps. |

`config_hash` is the load-bearing field for the runtime. It **includes the secret**, so rotating
an API key changes the hash, which invalidates both the tool cache and the cached agent graph
with no explicit bust.

### `user_mcp_credentials`

One row per server, `ON DELETE CASCADE`. Every value is encrypted with Fernet
(`cryptography`, already a dependency) under a key from `RELIVO_MCP_SECRET_KEY`.

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | UUID. Primary key. |
| `server_id` | string | FK → `user_mcp_servers.id`, unique. |
| `user_id` | string | Denormalized for per-user purge. |
| `key_id` | string | Which encryption key was used. Enables rotation in place. |
| `headers_ciphertext` | text/null | Encrypted JSON map of header name → value. Holds the `bearer` token too, as `Authorization`. |
| `oauth_client_secret_ciphertext` | text/null | Encrypted client secret. |
| `oauth_access_token_ciphertext` | text/null | Encrypted access token. |
| `oauth_refresh_token_ciphertext` | text/null | Encrypted refresh token. |
| `oauth_token_type` | string/null | Normally `Bearer`. |
| `oauth_expires_at` | datetime/null | Drives proactive refresh. |
| `oauth_granted_scopes` | array | Scopes actually granted, which may differ from requested. |

The `UserMcpServer.credential` relationship is `lazy="raise"` on purpose: a list query that
forgets to be explicit fails loudly instead of quietly pulling ciphertext into memory.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/users/{user_id}/mcp-servers` | List servers. Secrets masked. |
| `POST` | `/users/{user_id}/mcp-servers` | Register one server. |
| `POST` | `/users/{user_id}/mcp-servers/import` | Register many from a pasted `mcpServers` map. |
| `GET` | `/users/{user_id}/mcp-servers/{id}` | Read one server, including its discovered tools. |
| `PATCH` | `/users/{user_id}/mcp-servers/{id}` | Update. Omitting `auth` keeps existing credentials; sending it replaces them. |
| `DELETE` | `/users/{user_id}/mcp-servers/{id}` | Delete server and credentials. |
| `POST` | `/users/{user_id}/mcp-servers/{id}/test` | Connect now, refresh `tools`/`status`, return latency. |
| `POST` | `/users/{user_id}/mcp-servers/{id}/oauth/start` | Begin the OAuth flow; returns the URL to open. |
| `POST` | `/mcp-servers/oauth/callback` | Exchange the code and store tokens. |

Responses never contain a secret value. `auth` comes back as a summary:

```json
{ "type": "header", "configured": true, "header_names": ["x-api-key"] }
```

Create and test are separate calls on purpose. The screenshot's **Save** persists the row with
`status: "pending"`; **Save and Publish** additionally runs `/test` and only surfaces the server
to the agent once it reaches `ready`.

## Sample payloads

Every request body below validates against `src/schemas/user_mcp_server.py`, and every response
body is generated from it. Secrets shown are fake.

### `POST /users/{user_id}/mcp-servers`

**Header auth** — the `x-api-key` case:

```json
{
  "name": "meta-ads",
  "url": "https://mcp-preview.strique.io/meta-ads/mcp",
  "transport": "http",
  "auth": {
    "type": "header",
    "headers": { "x-api-key": "chnXDPDKtMC7Faoprk6u8euLK" }
  }
}
```

**Multiple headers** — a server that wants a key plus routing headers:

```json
{
  "name": "internal-analytics",
  "display_name": "Internal Analytics",
  "url": "https://mcp.internal.example.com/analytics/mcp",
  "auth": {
    "type": "header",
    "headers": {
      "x-api-key": "ak_live_9f2b",
      "x-workspace-id": "ws_18823",
      "x-env": "prod"
    }
  }
}
```

**No auth** — `auth` may be omitted entirely:

```json
{ "name": "deepwiki", "url": "https://mcp.deepwiki.com/mcp" }
```

**Bearer token:**

```json
{
  "name": "firecrawl",
  "url": "https://mcp.firecrawl.dev/v2/mcp",
  "auth": { "type": "bearer", "token": "fc-2b91c0d4e7f8" }
}
```

**OAuth, client id and secret from the user** (the screenshot's advanced panel). Authorization
and token URLs are discovered from the server, so they are optional:

```json
{
  "name": "notion",
  "display_name": "Notion",
  "url": "https://mcp.notion.com/mcp",
  "auth": {
    "type": "oauth",
    "client_id": "c_9a12f",
    "client_secret": "cs_7d3e",
    "scopes": ["read", "write"]
  }
}
```

**OAuth with dynamic client registration** — the user supplies nothing at all:

```json
{
  "name": "linear",
  "url": "https://mcp.linear.app/mcp",
  "auth": { "type": "oauth", "registration": "dynamic" }
}
```

**OAuth with endpoints pinned manually**, for servers that do not publish discovery metadata:

```json
{
  "name": "acme-crm",
  "url": "https://mcp.acme.com/mcp",
  "auth": {
    "type": "oauth",
    "client_id": "acme_client",
    "client_secret": "acme_secret",
    "authorization_url": "https://auth.acme.com/oauth/authorize",
    "token_url": "https://auth.acme.com/oauth/token",
    "scopes": ["crm.read"]
  }
}
```

**Every field set**, including SSE transport and a tool filter:

```json
{
  "name": "legacy-sse",
  "display_name": "Legacy SSE Server",
  "description": "Older server that only speaks SSE.",
  "url": "https://mcp.legacy.example.com/sse",
  "transport": "sse",
  "auth": { "type": "header", "headers": { "x-api-key": "legacy_key" } },
  "enabled": true,
  "allowed_tools": ["search_docs", "get_page"],
  "timeout_seconds": 60,
  "sse_read_timeout_seconds": 600
}
```

### `POST /users/{user_id}/mcp-servers/import`

This endpoint reads its body raw, so **JSON on its own is enough** — no wrapper, no renaming.
All four shapes below are accepted and normalize to the same stored row:

| Shape | Example |
|-------|---------|
| `servers` wrapper | `{"servers": {"meta-ads": {...}}}` |
| `mcpServers` wrapper | `{"mcpServers": {"meta-ads": {...}}}` |
| bare map | `{"meta-ads": {...}}` |
| single entry | `{"type": "http", "url": "..."}` — name derived from the URL |

Normalization rules applied on the way in:

- `type` and `transport` are both read; `http`, `streamable-http`, and `streamable_http` all mean
  Streamable HTTP, and `sse` stays SSE. An entry that names only `transport` is no longer
  silently treated as `http`.
- Keys are slugified — `"Meta Ads"` becomes `meta-ads` — because the name becomes part of a tool
  name. Two keys that collide after slugification are rejected rather than silently merged.
- A lone `Authorization: Bearer <token>` header is stored as `bearer` auth, not a raw header.
- Unknown keys (`disabled`, `note`, `env`, …) are ignored, so a block copied from another client
  needs no trimming.
- `command` / `args` entries are rejected with an explicit "local (stdio) MCP servers are not
  supported" message instead of a confusing "url is required".
- When no name is available it is derived from the URL: `.../meta-ads/mcp` yields `meta-ads`,
  and `https://mcp.notion.com/mcp` falls back to the host and yields `notion`.

The pasted `mcpServers` map, unchanged from what the user already has:

```json
{
  "servers": {
    "meta-ads": {
      "type": "http",
      "url": "https://mcp-preview.strique.io/meta-ads/mcp",
      "headers": { "x-api-key": "chnXDPDKtMC7Faoprk6u8euLK" }
    },
    "google-ads": {
      "type": "http",
      "url": "https://mcp-preview.strique.io/google-ads/mcp",
      "headers": { "x-api-key": "aBc123XyZ" }
    },
    "deepwiki": {
      "type": "http",
      "url": "https://mcp.deepwiki.com/mcp"
    }
  }
}
```

`headers` becomes `header` auth; no `headers` becomes `none`. `streamable-http` and
`streamable_http` are accepted as aliases for `http`. Unknown keys are ignored, so a block
copied from another client does not need trimming first.

### `PATCH /users/{user_id}/mcp-servers/{id}`

Every field is optional. **Omitting `auth` leaves stored credentials untouched** — that is the
difference between renaming a server and rotating its key.

```json
{ "auth": { "type": "header", "headers": { "x-api-key": "rotated_key_x82hd" } } }
```

```json
{ "enabled": false }
```

```json
{
  "display_name": "Meta Ads (prod)",
  "allowed_tools": ["list_campaigns", "get_insights"]
}
```

Sending `{"auth": {"type": "none"}}` deletes the stored credentials.

### Responses

`GET /users/{user_id}/mcp-servers` — note `auth` is a summary with no secret value in it:

```json
{
  "servers": [
    {
      "id": "8f1c2a44-1c3e-4c9a-9a0e-2d7b5f4a1e90",
      "user_id": "user_2abcDEF",
      "name": "meta-ads",
      "display_name": "Meta Ads",
      "description": null,
      "url": "https://mcp-preview.strique.io/meta-ads/mcp",
      "transport": "http",
      "auth": {
        "type": "header",
        "configured": true,
        "header_names": ["x-api-key"],
        "oauth_client_id": null,
        "oauth_registration": null,
        "scopes": [],
        "token_expires_at": null
      },
      "enabled": true,
      "status": "ready",
      "status_detail": null,
      "tools": [
        { "name": "list_campaigns", "description": "List ad campaigns." },
        { "name": "get_insights", "description": "Fetch performance insights." }
      ],
      "tool_count": 2,
      "allowed_tools": [],
      "timeout_seconds": 30.0,
      "sse_read_timeout_seconds": 300.0,
      "last_connected_at": "2026-08-04T09:12:33Z",
      "last_error_at": null,
      "created_at": "2026-08-04T09:12:33Z",
      "updated_at": "2026-08-04T09:12:33Z"
    },
    {
      "id": "b3d99c07-5a71-4f2c-8e0d-6c1b9a3f7e52",
      "user_id": "user_2abcDEF",
      "name": "notion",
      "display_name": "Notion",
      "description": null,
      "url": "https://mcp.notion.com/mcp",
      "transport": "http",
      "auth": {
        "type": "oauth",
        "configured": false,
        "header_names": [],
        "oauth_client_id": "c_9a12f",
        "oauth_registration": "manual",
        "scopes": ["read", "write"],
        "token_expires_at": null
      },
      "enabled": true,
      "status": "unauthorized",
      "status_detail": "OAuth consent required",
      "tools": [],
      "tool_count": 0,
      "allowed_tools": [],
      "timeout_seconds": 30.0,
      "sse_read_timeout_seconds": 300.0,
      "last_connected_at": null,
      "last_error_at": null,
      "created_at": "2026-08-04T09:12:33Z",
      "updated_at": "2026-08-04T09:12:33Z"
    }
  ]
}
```

`POST /users/{user_id}/mcp-servers/{id}/test`:

```json
{
  "server_id": "8f1c2a44-1c3e-4c9a-9a0e-2d7b5f4a1e90",
  "status": "ready",
  "tools": [
    { "name": "list_campaigns", "description": "List ad campaigns." },
    { "name": "get_insights", "description": "Fetch performance insights." }
  ],
  "tool_count": 2,
  "latency_ms": 412,
  "error": null
}
```

```json
{
  "server_id": "8f1c2a44-1c3e-4c9a-9a0e-2d7b5f4a1e90",
  "status": "error",
  "tools": [],
  "tool_count": 0,
  "latency_ms": null,
  "error": "401 Unauthorized from https://mcp-preview.strique.io/meta-ads/mcp"
}
```

`POST /users/{user_id}/mcp-servers/{id}/oauth/start` — the frontend opens `authorization_url`:

```json
{
  "server_id": "b3d99c07-5a71-4f2c-8e0d-6c1b9a3f7e52",
  "authorization_url": "https://auth.notion.com/oauth/authorize?response_type=code&client_id=c_9a12f&code_challenge=...&resource=https%3A%2F%2Fmcp.notion.com%2Fmcp",
  "state": "st_7f2c9e1b",
  "expires_in_seconds": 600
}
```

`POST /mcp-servers/oauth/callback` — request body built from the redirect query string:

```json
{ "state": "st_7f2c9e1b", "code": "ac_9182hd", "iss": "https://auth.notion.com" }
```

### Rejected payloads

These fail validation at the API boundary, before anything is stored or connected to:

| Payload | Why it is rejected |
|---------|--------------------|
| `{"name": "x", "url": "http://mcp.example.com/mcp"}` | `url must be an absolute https:// URL` |
| `{"name": "MetaAds", ...}` | name must match `^[a-z0-9][a-z0-9_-]{0,63}$` |
| `{"name": "meta ads", ...}` | same — no spaces, it becomes part of a tool name |
| `{"url": "https://a.example.com/mcp#frag"}` | `url must not contain a fragment` |
| `"auth": {"type": "header", "headers": {"Host": "evil.example.com"}}` | `header 'Host' is reserved by the transport` |
| `"auth": {"type": "header", "headers": {"Content-Type": "text/plain"}}` | reserved — the transport owns it |
| `"auth": {"type": "header", "headers": {}}` | `header` auth needs at least one header |
| `"auth": {"type": "oauth"}` | `client_id is required when registration is 'manual'` |
| `"auth": {"type": "basic", "username": "u", "password": "p"}` | unknown auth type |
| `{"servers": {"local": {"command": "npx", "args": [...]}}}` | stdio servers are out of scope; `url` is required |
| `{"timeout_seconds": 900}` | capped at 300 |

## Security

The user controls the URL and the headers, so both are hostile input.

1. **SSRF guard before any connection** (`src/utils/mcp_url.py`). Requires `https`, rejects
   `localhost` and blocked names, resolves DNS, and rejects every resolved IP that is private,
   loopback, link-local, reserved, multicast, or unspecified — that last set is what blocks
   `169.254.169.254`. It runs on create, on update, and again in `build_client_config` before
   each connection, so a URL that resolved publicly at registration is re-checked at use.
   **Still open:** the validated IP is not yet pinned for the actual connection, so a
   DNS-rebinding window remains between the check and the request.
2. **Reserved headers rejected.** `Host`, `Content-Length`, `Transfer-Encoding`,
   `Mcp-Session-Id`, and friends are refused at the schema boundary
   (`RESERVED_HEADER_NAMES`), so a user cannot break or redirect the transport.
3. **Encryption at rest**, per the table above. Nothing decrypts outside the tool loader.
4. **Caps**: 10 headers per server, 4 KB per header value, 20 servers per import,
   `RELIVO_MCP_MAX_SERVERS` (default 20) per user, and `RELIVO_MCP_MAX_TOOLS` (default 64) per
   server — an MCP server can advertise hundreds of tools and blow up the prompt.
5. **Fault isolation.** One unreachable server must never fail a chat turn: log, mark
   `status="error"`, and continue with the remaining tools.
6. **Prompt-injection surface.** Third-party tool descriptions enter the system prompt. Keep
   custom MCP tools namespaced (`mcp__<server>__<tool>`) so the model and the transcript always
   show which server a tool came from.

## Connection flow

`POST /{id}/test` is the connection path, and `UserMcpService.load_tools` is what the agent
wiring will reuse:

1. Re-run the SSRF guard on the stored URL.
2. Decrypt the credential row and turn it into headers — the stored map for `header`/`bearer`,
   `Authorization: <type> <access_token>` for `oauth`.
3. Build the `MultiServerMCPClient` entry: `transport` is translated to the adapter's spelling
   (`http` → `streamable_http`, `sse` → `sse`), plus `url`, `timeout`, `sse_read_timeout`, and
   `headers`.
4. Discover tools, apply `allowed_tools`, cap at `RELIVO_MCP_MAX_TOOLS`, and namespace each as
   `mcp__<server>__<tool>`.
5. Persist the outcome: `ready` with the tool list and `last_connected_at`, or `error` /
   `unauthorized` with `status_detail` and `last_error_at`.

A failed connection returns **200 with the reason in the body**, not a 5xx — the call succeeded,
the server is what is broken, and the UI needs the message to show the user.

An OAuth server with no stored access token short-circuits to `unauthorized` without dialling
out, since the flow that would populate the token is not built yet.

## Runtime wiring

Tools are bound into a LangGraph agent at build time, and the Orchestrator is a process-wide
singleton — so a user's MCP tools cannot be added to the shared agent without handing them to
everyone. Instead the agent is **resolved per turn**:

1. `ChatService.stream_chat` resolves `user_id` from the conversation, then calls its
   `agent_resolver` ([chat_service.py](../src/services/chat_service.py) `_resolve_agent`).
2. `resolve_agent_for_user` ([orchestrator.py](../src/agents/orchestrator.py)) loads that user's
   **enabled** servers. No servers means the shared base agent is returned untouched — the
   common path costs one indexed query and nothing else.
3. **Tool cache** ([mcp_registry.py](../src/tools/mcp_registry.py)), keyed by `config_hash`,
   TTL `RELIVO_MCP_TOOL_CACHE_TTL` (default 300s). A miss connects via `MultiServerMCPClient`;
   concurrent misses for the same key are single-flighted through a per-key lock.
4. **Agent cache**, an LRU keyed by `(BASE_AGENT_VERSION, *sorted config_hashes)`, capped at
   `RELIVO_MCP_MAX_CACHED_AGENTS` (default 32).

### Why cross-user cache sharing is safe

`config_hash` includes the server's secret. Two users with the same URL but different API keys
hash differently and never share a cache entry. Two users with byte-identical config *and*
credentials do share one graph — safe, because the tool set is the same object either way and
there is nothing of one user's to leak into the other's. The signature is built only from the
requesting user's own rows, so one user's servers can never enter another user's key.

### Failure behaviour

Every layer degrades to the base agent rather than failing the turn: a database error in the
server lookup, a dead MCP server (skipped individually, others still load), all servers failing,
or the resolver itself raising. Each is logged; the user still gets a reply.

### Invalidation

Rotating a credential changes `config_hash`, which changes both cache keys — no explicit bust
needed. `update_server` and `delete_server` additionally call `registry.invalidate()` on the old
hash so a rotated-away credential is not served for up to the TTL.

### Shared checkpointer

`BaseAgent` defaults to its own `InMemorySaver`, and conversation history lives there keyed by
`thread_id` — `_agent_prompt` sends only the current turn. Every agent instance is therefore
built with one shared checkpointer, so a user who registers a server mid-conversation does not
land on a graph with empty history.

Sections 3–7 of `notebooks/dynamic_mcp_prototype.ipynb` prototype the same two caches offline.

## Prior art

- **MCP authorization spec** — OAuth 2.1 with PKCE, protected resource metadata (RFC 9728) for
  discovery, RFC 8707 `resource` binding, and dynamic client registration (RFC 7591, now
  deprecated in favour of client ID metadata documents). The spec covers OAuth only; static API
  keys are left to the client, which is why `header` auth is our own extension.
  <https://modelcontextprotocol.io/specification/draft/basic/authorization>
- **LibreChat** — the closest open-source analogue, and the model for splitting auth into
  `headers` / `apiKey` / `oauth` rather than assuming OAuth. It also supports per-user
  credentials via `customUserVars` and placeholder substitution in headers, worth copying later
  if a server needs a value only the end user has.
  <https://www.librechat.ai/docs/configuration/librechat_yaml/object_structure/mcp_servers>
- **VS Code `mcp.json`** — where `{"type": "http", "url": ..., "headers": {...}}` comes from.
  Keeping the import format identical means users paste what they already have.
  <https://code.visualstudio.com/docs/copilot/customization/mcp-servers>
- **`langchain-mcp-adapters` 0.3.0** — the connection TypedDicts we serialize into
  (`StreamableHttpConnection`, `SSEConnection`: `url`, `headers`, `timeout`, `sse_read_timeout`,
  `auth`). The DB columns are a deliberate one-to-one mapping onto these fields.
