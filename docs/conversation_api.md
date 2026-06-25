# Conversation API

The conversation API stores chat history. The `/chat` streaming endpoint also stores completed
tool-using agent responses when `thread_id` is an existing conversation UUID.

A conversation can contain many messages. A message can be a user message or an agent message. A single agent message can contain answer text, multiple tool calls, and multiple reasoning records.

## Data Model

Conversation:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Conversation UUID. |
| `user_id` | string | Required user identifier that owns the conversation. |
| `title` | string/null | Optional display title. |
| `created_at` | datetime | Creation timestamp. |
| `updated_at` | datetime | Last update timestamp. |

Message:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Message UUID. |
| `conversation_id` | string | Parent conversation UUID. |
| `role` | `user` or `agent` | Message author. |
| `text` | string/null | Text message or assistant answer text. |
| `attachments` | object[] | File/image references stored on `metadata.attachments`. |
| `metadata` | object/null | Extra structured metadata. |
| `created_at` | datetime | Creation timestamp. |
| `updated_at` | datetime | Last update timestamp. |

Tool call:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Tool call row UUID. |
| `message_id` | string | Parent message UUID. |
| `tool_call_id` | string/null | Provider/tool-call id, when available. |
| `name` | string | Tool name. |
| `arguments` | object/null | Tool input arguments. |
| `result` | object/string/null | Tool result or error payload. |
| `status` | `pending`, `running`, `completed`, or `failed` | Tool execution status. |
| `sequence` | integer | Ordering within the message. |
| `created_at` | datetime | Creation timestamp. |
| `updated_at` | datetime | Last update timestamp. |

Reasoning entry:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Reasoning row UUID. |
| `message_id` | string | Parent message UUID. |
| `content` | string | Reasoning content or reasoning summary record. |
| `summary` | string/null | Short label or summary. |
| `metadata` | object/null | Extra structured metadata. |
| `sequence` | integer | Ordering within the message. |
| `created_at` | datetime | Creation timestamp. |
| `updated_at` | datetime | Last update timestamp. |

## Conversation CRUD

### List Conversations

```http
GET /conversations
```

Optional query params:

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | string | Return only conversations for this user. |

Returns:

```json
[
  {
    "id": "conversation-id",
    "user_id": "user-123",
    "title": "Planning",
    "created_at": "2026-06-05T10:00:00Z",
    "updated_at": "2026-06-05T10:00:00Z"
  }
]
```

### Create Conversation

```http
POST /conversations
```

Body:

```json
{
  "user_id": "user-123",
  "title": "Planning"
}
```

### Get Conversation With Messages

```http
GET /conversations/{conversation_id}
```

### Update Conversation

```http
PATCH /conversations/{conversation_id}
```

Body:

```json
{
  "title": "Updated planning"
}
```

### Delete Conversation

```http
DELETE /conversations/{conversation_id}
```

Returns `204 No Content`.

## Message CRUD

### List Messages

```http
GET /conversations/{conversation_id}/messages
```

### Create User Text Message

```http
POST /conversations/{conversation_id}/messages
```

Body:

```json
{
  "role": "user",
  "text": "Help me plan my day"
}
```

### Create User Message With Attachments

```http
POST /conversations/{conversation_id}/messages
```

Use the attachment objects returned by `POST /ai/uploads`. Text is optional when at least one
attachment is present. The backend stores these references in `metadata.attachments` and also
returns them as a first-class `attachments` field for frontend rendering.

Body:

```json
{
  "role": "user",
  "text": "What is in this image?",
  "attachments": [
    {
      "url": "https://s3-presigned-url.example/screenshot.png",
      "mediaType": "image/png",
      "title": "screenshot.png"
    }
  ]
}
```

Attachment-only body:

```json
{
  "role": "user",
  "attachments": [
    {
      "url": "https://s3-presigned-url.example/screenshot.png",
      "mediaType": "image/png",
      "title": "screenshot.png"
    }
  ]
}
```

### Create Agent Message With Multiple Tool Calls And Reasoning Entries

```http
POST /conversations/{conversation_id}/messages
```

Body:

```json
{
  "role": "agent",
  "text": "I checked context and calendar before answering.",
  "tool_calls": [
    {
      "tool_call_id": "call_1",
      "name": "get_demo_context",
      "arguments": {
        "topic": "planning"
      },
      "result": {
        "content": "planning context"
      },
      "sequence": 0
    },
    {
      "tool_call_id": "call_2",
      "name": "get_calendar",
      "arguments": {
        "date": "2026-06-05"
      },
      "status": "completed",
      "sequence": 1
    }
  ],
  "reasoning_entries": [
    {
      "content": "Need planning context first.",
      "summary": "context",
      "sequence": 0
    },
    {
      "content": "Need calendar constraints next.",
      "summary": "calendar",
      "sequence": 1
    }
  ],
  "metadata": {
    "node": "model"
  }
}
```

### Create Tool Call On Existing Message

```http
POST /conversations/{conversation_id}/messages/{message_id}/tool-calls
```

Body:

```json
{
  "tool_call_id": "call_123",
  "name": "get_demo_context",
  "arguments": {
    "topic": "planning"
  },
  "status": "completed",
  "sequence": 0
}
```

Tool call CRUD:

```http
GET /conversations/{conversation_id}/messages/{message_id}/tool-calls
GET /conversations/{conversation_id}/messages/{message_id}/tool-calls/{tool_call_id}
PATCH /conversations/{conversation_id}/messages/{message_id}/tool-calls/{tool_call_id}
DELETE /conversations/{conversation_id}/messages/{message_id}/tool-calls/{tool_call_id}
```

### Create Reasoning Entry On Existing Message

```http
POST /conversations/{conversation_id}/messages/{message_id}/reasoning
```

Body:

```json
{
  "content": "The user needs a daily plan, so first collect goals and constraints.",
  "summary": "planning constraints",
  "sequence": 0
}
```

Reasoning CRUD:

```http
GET /conversations/{conversation_id}/messages/{message_id}/reasoning
GET /conversations/{conversation_id}/messages/{message_id}/reasoning/{reasoning_id}
PATCH /conversations/{conversation_id}/messages/{message_id}/reasoning/{reasoning_id}
DELETE /conversations/{conversation_id}/messages/{message_id}/reasoning/{reasoning_id}
```

### Get Message

```http
GET /conversations/{conversation_id}/messages/{message_id}
```

### Update Message

```http
PATCH /conversations/{conversation_id}/messages/{message_id}
```

Body:

```json
{
  "message_type": "text",
  "text": "Updated message text"
}
```

### Delete Message

```http
DELETE /conversations/{conversation_id}/messages/{message_id}
```

Returns `204 No Content`.

## Errors

Missing conversations:

```json
{
  "status": 404,
  "message": "conversation not found",
  "error_tag": "conversation_not_found"
}
```

Missing messages:

```json
{
  "status": 404,
  "message": "message not found",
  "error_tag": "message_not_found"
}
```
