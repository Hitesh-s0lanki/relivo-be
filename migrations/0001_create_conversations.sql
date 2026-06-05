CREATE TABLE conversations (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(200) NOT NULL,
    title VARCHAR(200),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE conversation_messages (
    id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    text TEXT,
    message_metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE conversation_message_tool_calls (
    id VARCHAR(36) PRIMARY KEY,
    message_id VARCHAR(36) NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
    tool_call_id VARCHAR(200),
    name VARCHAR(200) NOT NULL,
    arguments JSONB,
    result JSONB,
    status VARCHAR(30) NOT NULL,
    sequence INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE TABLE conversation_message_reasoning_entries (
    id VARCHAR(36) PRIMARY KEY,
    message_id VARCHAR(36) NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    summary TEXT,
    reasoning_metadata JSONB,
    sequence INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX ix_conversation_messages_conversation_id
    ON conversation_messages(conversation_id);

CREATE INDEX ix_conversations_user_id
    ON conversations(user_id);

CREATE INDEX ix_conversation_messages_role
    ON conversation_messages(role);

CREATE INDEX ix_conversation_message_tool_calls_message_id
    ON conversation_message_tool_calls(message_id);

CREATE INDEX ix_conversation_message_tool_calls_tool_call_id
    ON conversation_message_tool_calls(tool_call_id);

CREATE INDEX ix_conversation_message_tool_calls_name
    ON conversation_message_tool_calls(name);

CREATE INDEX ix_conversation_message_tool_calls_status
    ON conversation_message_tool_calls(status);

CREATE INDEX ix_conversation_message_reasoning_entries_message_id
    ON conversation_message_reasoning_entries(message_id);
