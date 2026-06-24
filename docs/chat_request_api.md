# Chat Request API

## Overview

`POST /chat` streams a chat response from the Relivo chat agent using Vercel AI SDK UI message stream Server-Sent Events.

Use this endpoint when a client sends a user message and needs to receive response chunks as they are generated.

This API can be consumed directly from a Vercel frontend with `fetch`. You do not need to use Vercel AI SDK `useChat` unless you specifically want that client abstraction.

For detailed Vercel AI SDK compatibility notes, see `docs/vercel_ai_sdk_chat_integration.md`.

## Endpoint

```http
POST /chat
```

Base URL for local development:

```text
http://localhost:8000
```

Full local URL:

```text
http://localhost:8000/chat
```

## Request

Headers:

| Header | Value |
|--------|-------|
| `Content-Type` | `application/json` |

Body:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `user_message` | string | Yes | - | User message to send to the chat agent. Must be 1-8000 characters and cannot be blank. |
| `thread_id` | string | No | `demo` | Conversation thread identifier used by agent memory/checkpointing. |
| `stream_mode` | string[] | No | `["updates", "messages"]` | Agent stream event types to include. Supported values are `updates` and `messages`. |

When `thread_id` is an existing conversation UUID and the agent uses tools, the backend also stores the completed agent response with its tool calls in the conversation API. Non-UUID thread ids and no-tool chat turns are streamed only.

Example:

```json
{
  "user_message": "Help me plan my day",
  "thread_id": "user-123",
  "stream_mode": ["updates", "messages"]
}
```

Minimal example:

```json
{
  "user_message": "Hello"
}
```

## Response

The response is streamed as Server-Sent Events.

Headers:

| Header | Value | Purpose |
|--------|-------|---------|
| `Content-Type` | `text/event-stream` | Indicates an SSE stream. |
| `x-vercel-ai-ui-message-stream` | `v1` | Indicates a Vercel AI SDK UI message stream. |
| `Cache-Control` | `no-cache` | Prevents response caching. |
| `Connection` | `keep-alive` | Keeps the streaming connection open. |
| `X-Accel-Buffering` | `no` | Disables buffering behind compatible reverse proxies. |

## Stream Parts

Each SSE frame has this format:

```text
data: <json_payload>
```

The stream ends with:

```text
data: [DONE]
```

Parts:

| Part `type` | Description | Payload |
|-------------|-------------|---------|
| `start` | Stream starts. | Includes `messageId`. |
| `text-start` | Assistant text block starts. | Includes text block `id`. |
| `text-delta` | Assistant text chunk is available. | Includes text block `id` and `delta`. |
| `text-end` | Assistant text block ends. | Includes text block `id`. |
| `tool-input-available` | Agent emitted a complete tool call input. | Includes `toolCallId`, `toolName`, and `input`. |
| `data-tool-call-chunk` | Custom Relivo streamed tool-call chunk data. | Includes `node`, `tool_call_chunks`, and `metadata`. |
| `data-agent-update` | Custom Relivo agent graph update or tool output. | Includes normalized agent update data. |
| `data-agent-event` | Custom fallback for unknown agent event types. | Includes normalized event data. |
| `error` | Stream fails after the connection opens. | Includes `errorText` and `data` with `status`, `message`, and `error_tag`. |
| `finish` | Stream closes. | `{ "type": "finish" }` |

Example stream:

```text
data: {"type":"start","messageId":"user-123"}

data: {"type":"text-start","id":"text-1"}

data: {"type":"text-delta","id":"text-1","delta":"Hello"}

data: {"type":"text-end","id":"text-1"}

data: {"type":"finish"}

data: [DONE]
```

For a full captured stream with tool-call chunks, tool input, tool result data, text deltas, and final agent update, see:

```text
docs/chat_stream_reference.sse
```

## cURL

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"user_message":"Hello","thread_id":"user-123"}'
```

## JavaScript Client

```js
const response = await fetch("http://localhost:8000/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    user_message: "Hello",
    thread_id: "user-123",
  }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  console.log(decoder.decode(value, { stream: true }));
}
```

## Vercel Frontend Client

Use this approach when the frontend is hosted on Vercel but you do not want to use Vercel AI SDK's native `useChat` client.

Because `/chat` is a `POST` streaming endpoint, use `fetch` with `ReadableStream`. Do not use browser `EventSource`, because `EventSource` only supports `GET`.

```ts
type ChatRequest = {
  user_message: string;
  thread_id?: string;
  stream_mode?: Array<"updates" | "messages">;
};

type ChatStreamPart =
  | { type: "start"; messageId: string }
  | { type: "text-start"; id: string }
  | { type: "text-delta"; id: string; delta: string }
  | { type: "text-end"; id: string }
  | {
      type: "tool-input-available";
      toolCallId: string;
      toolName: string;
      input: unknown;
    }
  | { type: "data-tool-call-chunk"; data: unknown }
  | { type: "data-agent-update"; data: unknown }
  | { type: "data-agent-event"; data: unknown }
  | {
      type: "error";
      errorText: string;
      data: {
        status: number;
        message: string;
        error_tag: string;
      };
    }
  | { type: "finish" };
```

Client helper:

```ts
export async function streamRelivoChat(
  request: ChatRequest,
  onPart: (part: ChatStreamPart) => void,
) {
  const response = await fetch(`${process.env.NEXT_PUBLIC_RELIVO_API_URL}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      stream_mode: ["updates", "messages"],
      ...request,
    }),
  });

  if (!response.ok) {
    throw new Error(`Chat request failed: ${response.status}`);
  }

  if (!response.body) {
    throw new Error("Chat response body is empty");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const dataLine = frame
        .split("\n")
        .find(line => line.startsWith("data: "));

      if (!dataLine) continue;

      const data = dataLine.slice("data: ".length);
      if (data === "[DONE]") return;

      onPart(JSON.parse(data) as ChatStreamPart);
    }
  }
}
```

Example usage:

```ts
let assistantText = "";

await streamRelivoChat(
  {
    user_message: "Help me plan my day",
    thread_id: "user-123",
  },
  part => {
    if (part.type === "text-delta") {
      assistantText += part.delta;
    }

    if (part.type === "error") {
      console.error(part.data.error_tag, part.data.message);
    }
  },
);
```

Environment variable for Vercel frontend:

```text
NEXT_PUBLIC_RELIVO_API_URL=https://your-relivo-api.example.com
```

For local development:

```text
NEXT_PUBLIC_RELIVO_API_URL=http://localhost:8000
```

## Optional Vercel AI SDK Client

The response also uses AI SDK UI message stream frames and includes `x-vercel-ai-ui-message-stream: v1`.

If you later decide to use Vercel AI SDK `useChat`, configure the transport request body because Relivo accepts `user_message` instead of the SDK's default `messages` request.

## Validation Errors

The API returns `422 Unprocessable Entity` when:

- `user_message` is missing.
- `user_message` is empty.
- `user_message` contains only whitespace.
- `user_message` is longer than 8000 characters.
- `thread_id` is empty or longer than 200 characters.
- `stream_mode` contains unsupported values.

Example error for a blank message:

```json
{
  "status": 422,
  "message": "user_message cannot be blank",
  "error_tag": "blank_user_message"
}
```

All client-facing error payloads use this shape:

```json
{
  "status": 500,
  "message": "chat stream failed",
  "error_tag": "chat_stream_failed"
}
```

## Runtime Behavior

When `OPENAI_API_KEY` is configured, the service uses a reasoning-capable OpenAI model from `RELIVO_CHAT_MODEL`.

Default model:

```text
gpt-5-mini
```

Reasoning configuration:

| Variable | Default | Description |
|----------|---------|-------------|
| `RELIVO_CHAT_MODEL` | `gpt-5-mini` | OpenAI chat model used by the Relivo chat agent. |
| `RELIVO_CHAT_REASONING_EFFORT` | `low` | Reasoning effort passed to the model. |
| `RELIVO_CHAT_USE_RESPONSES_API` | `true` | Uses OpenAI Responses API mode for reasoning models. |

The agent uses reasoning internally for multi-step planning, tool selection, and ambiguous requests. Private reasoning is not streamed to the frontend; the stream only includes tool/progress parts and answer text.

Example environment:

```text
OPENAI_API_KEY=sk-your-key-here
RELIVO_CHAT_MODEL=gpt-5-mini
RELIVO_CHAT_REASONING_EFFORT=low
RELIVO_CHAT_USE_RESPONSES_API=true
```

When `OPENAI_API_KEY` is not configured, the service uses a local fake chat model and streams a demo fallback response.
