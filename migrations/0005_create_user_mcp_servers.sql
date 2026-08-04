CREATE TABLE IF NOT EXISTS user_mcp_servers (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(200) NOT NULL,
    name VARCHAR(64) NOT NULL,
    display_name VARCHAR(200),
    description TEXT,
    url VARCHAR(2048) NOT NULL,
    transport VARCHAR(20) NOT NULL DEFAULT 'http',
    auth_type VARCHAR(20) NOT NULL DEFAULT 'none',
    auth_header_names JSONB NOT NULL DEFAULT '[]'::jsonb,
    oauth_client_id VARCHAR(500),
    oauth_authorization_url VARCHAR(2048),
    oauth_token_url VARCHAR(2048),
    oauth_registration VARCHAR(20) NOT NULL DEFAULT 'manual',
    oauth_scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
    oauth_metadata JSONB,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    status_detail TEXT,
    tools JSONB NOT NULL DEFAULT '[]'::jsonb,
    tool_count INTEGER NOT NULL DEFAULT 0,
    allowed_tools JSONB NOT NULL DEFAULT '[]'::jsonb,
    timeout_seconds DOUBLE PRECISION NOT NULL DEFAULT 30,
    sse_read_timeout_seconds DOUBLE PRECISION NOT NULL DEFAULT 300,
    config_hash VARCHAR(64) NOT NULL,
    last_connected_at TIMESTAMP WITH TIME ZONE,
    last_error_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_user_mcp_servers_user_name UNIQUE (user_id, name),
    CONSTRAINT ck_user_mcp_servers_transport CHECK (transport IN ('http', 'sse')),
    CONSTRAINT ck_user_mcp_servers_auth_type CHECK (
        auth_type IN ('none', 'bearer', 'header', 'oauth')
    ),
    CONSTRAINT ck_user_mcp_servers_status CHECK (
        status IN ('pending', 'ready', 'error', 'unauthorized')
    ),
    CONSTRAINT ck_user_mcp_servers_oauth_registration CHECK (
        oauth_registration IN ('manual', 'dynamic')
    ),
    CONSTRAINT ck_user_mcp_servers_url_https CHECK (url LIKE 'https://%'),
    CONSTRAINT ck_user_mcp_servers_timeouts CHECK (
        timeout_seconds > 0 AND sse_read_timeout_seconds > 0
    )
);

CREATE TABLE IF NOT EXISTS user_mcp_credentials (
    id VARCHAR(36) PRIMARY KEY,
    server_id VARCHAR(36) NOT NULL REFERENCES user_mcp_servers(id) ON DELETE CASCADE,
    user_id VARCHAR(200) NOT NULL,
    key_id VARCHAR(50) NOT NULL DEFAULT 'v1',
    headers_ciphertext TEXT,
    oauth_client_secret_ciphertext TEXT,
    oauth_access_token_ciphertext TEXT,
    oauth_refresh_token_ciphertext TEXT,
    oauth_token_type VARCHAR(30),
    oauth_expires_at TIMESTAMP WITH TIME ZONE,
    oauth_granted_scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_user_mcp_credentials_server_id UNIQUE (server_id)
);

CREATE INDEX IF NOT EXISTS ix_user_mcp_servers_user_id
    ON user_mcp_servers(user_id);

CREATE INDEX IF NOT EXISTS ix_user_mcp_servers_user_enabled
    ON user_mcp_servers(user_id, enabled);

CREATE INDEX IF NOT EXISTS ix_user_mcp_servers_config_hash
    ON user_mcp_servers(config_hash);

CREATE INDEX IF NOT EXISTS ix_user_mcp_servers_status
    ON user_mcp_servers(status);

CREATE INDEX IF NOT EXISTS ix_user_mcp_credentials_user_id
    ON user_mcp_credentials(user_id);
