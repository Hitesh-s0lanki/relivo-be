# Vercel AI SDK Chat Integration

This document captures how the current Relivo `POST /chat` API maps to Vercel AI SDK UI usage.

Sources checked:

- Vercel AI SDK v6 Stream Protocols: https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol
- Vercel AI SDK v6 Transport: https://ai-sdk.dev/docs/ai-sdk-ui/transport
- Vercel AI SDK v6 `useChat` reference: https://ai-sdk.dev/docs/reference/ai-sdk-ui/use-chat
- Vercel AI SDK v6 Reading UI Message Streams: https://ai-sdk.dev/docs/ai-sdk-ui/reading-ui-message-streams

## Current Relivo Status

The current `/chat` endpoint returns Vercel AI SDK UI message stream Server-Sent Events:

```text
data: {"type":"text-delta","id":"text-1","delta":"Hello"}
```

The backend also returns the AI SDK UI message stream header:

```text
x-vercel-ai-ui-message-stream: v1
```

## Current `/chat` Input

Relivo backend input:

```json
{
  "user_message": "Help me plan my day",
  "thread_id": "user-123",
  "stream_mode": ["updates", "messages"]
}
```

Fields:

| Field | Type | Required | Default | Meaning |
|-------|------|----------|---------|---------|
| `user_message` | string | Yes | - | Text prompt sent to the Relivo chat agent. |
| `thread_id` | string | No | `demo` | Conversation memory/checkpoint key. |
| `stream_mode` | array | No | `["updates", "messages"]` | LangGraph stream modes to include. |

`stream_mode` values:

| Value | Meaning |
|-------|---------|
| `messages` | Streams model/tool message chunks. Use this to render assistant text as it arrives. |
| `updates` | Streams agent step updates. Use this for tool calls, tool results, and graph progress. |

## Current `/chat` Output

The current Relivo output is unnamed SSE data frames:

```text
data: <json_payload>
```

The stream terminates with:

```text
data: [DONE]
```

Stream parts:

| Part type | Payload |
|-----------|---------|
| `start` | `{ "type": "start", "messageId": "user-123" }` |
| `text-start` | `{ "type": "text-start", "id": "text-1" }` |
| `text-delta` | `{ "type": "text-delta", "id": "text-1", "delta": "Hello" }` |
| `text-end` | `{ "type": "text-end", "id": "text-1" }` |
| `tool-input-available` | `{ "type": "tool-input-available", "toolCallId": "...", "toolName": "...", "input": {} }` |
| `data-tool-call-chunk` | Custom Relivo streamed tool-call chunk data. |
| `data-agent-update` | Custom Relivo agent graph update or tool output. |
| `data-agent-event` | Custom Relivo fallback event data. |
| `error` | `{ "type": "error", "errorText": "chat stream failed", "data": { "status": 500, "message": "chat stream failed", "error_tag": "chat_stream_failed" } }` |
| `finish` | `{ "type": "finish" }` |

Raw reference stream:

```text
docs/chat_stream_reference.sse
```

## Vercel AI SDK `useChat` Input Shape

`useChat` sends chat requests through a transport. By default it posts to `/api/chat`. The request can be customized with `DefaultChatTransport` and `prepareSendMessagesRequest`.

AI SDK UI normally works with `UIMessage[]`:

```ts
type AiSdkChatRequest = {
  messages: UIMessage[];
};
```

Useful `useChat` request controls:

| Option | Purpose |
|--------|---------|
| `transport` | Controls where and how requests are sent. |
| `api` | API endpoint, default `/api/chat`. |
| `headers` | Extra HTTP headers. |
| `body` | Extra JSON properties sent with requests. |
| `prepareSendMessagesRequest` | Converts/customizes the outgoing request body. |
| `sendMessage` | Sends a new user message. |
| `regenerate` | Regenerates an assistant message. |
| `stop` | Aborts the current stream. |
| `resumeStream` | Resumes an interrupted stream when supported. |
| `addToolOutput` | Adds client-side tool output when client tools are used. |

## Recommended Frontend Adapter For Current Relivo API

Because Relivo currently accepts `user_message` instead of AI SDK `messages`, use `prepareSendMessagesRequest` to transform the outgoing body.

```ts
import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";

const chat = useChat({
  transport: new DefaultChatTransport({
    api: "http://localhost:8000/chat",
    prepareSendMessagesRequest: ({ id, messages }) => {
      const lastMessage = messages[messages.length - 1];
      const text = lastMessage?.parts
        ?.filter(part => part.type === "text")
        .map(part => part.text)
        .join("");

      return {
        body: {
          user_message: text ?? "",
          thread_id: id,
          stream_mode: ["updates", "messages"],
        },
      };
    },
  }),
});
```

The response is already emitted as AI SDK UI message stream frames, so this adapter is only needed to convert AI SDK `messages` input into Relivo's `user_message` input.

## Vercel AI SDK UI Message Stream Output Shape

The AI SDK UI data stream protocol uses SSE frames like:

```text
data: {"type":"start","messageId":"msg-1"}
data: {"type":"text-start","id":"text-1"}
data: {"type":"text-delta","id":"text-1","delta":"Hello"}
data: {"type":"text-end","id":"text-1"}
data: {"type":"finish"}
data: [DONE]
```

Common stream parts:

| Part type | Purpose |
|-----------|---------|
| `start` | Starts a new assistant message. |
| `text-start` | Starts a text block. |
| `text-delta` | Streams incremental text. |
| `text-end` | Ends a text block. |
| `data-*` | Streams custom typed data. |
| `error` | Adds an error part to the message. |
| `tool-input-start` | Starts tool input streaming. |
| `tool-input-delta` | Streams partial tool input text. |
| `tool-input-available` | Tool input is complete. |
| `tool-output-available` | Tool output is available. |
| `start-step` | Starts a model/tool step. |
| `finish-step` | Finishes a model/tool step. |
| `finish` | Finishes the message. |
| `abort` | Indicates client/server stream abort. |
| `[DONE]` | Terminates the stream. |

## Mapping Agent Chunks To AI SDK Stream Parts

The backend maps LangGraph agent chunks to AI SDK stream parts like this:

| Agent chunk | AI SDK stream part |
|-------------|--------------------|
| stream open | `data: {"type":"start","messageId":"user-123"}` |
| first assistant text chunk | `data: {"type":"text-start","id":"text-1"}` |
| each assistant text chunk | `data: {"type":"text-delta","id":"text-1","delta":"..."}` |
| assistant text complete | `data: {"type":"text-end","id":"text-1"}` |
| update with tool calls | `data: {"type":"tool-input-available", ...}` |
| streamed tool call chunks | `data: {"type":"data-tool-call-chunk", ...}` |
| tool result or graph progress | `data: {"type":"data-agent-update", ...}` |
| stream error | `data: {"type":"error","errorText":"chat stream failed","data": {...}}` |
| stream close | `data: {"type":"finish"}` then `data: [DONE]` |

## Backend Compatibility Checklist

Relivo `/chat` should keep these compatibility details:

1. Keep `Content-Type: text/event-stream`.
2. Add `x-vercel-ai-ui-message-stream: v1`.
3. Emit unnamed SSE frames with `data: {"type": ...}`.
4. End with `data: [DONE]`.
5. Convert Relivo tool calls and tool results into AI SDK tool parts or custom `data-*` parts.

Example compatible stream:

```text
data: {"type":"start","messageId":"user-123"}

data: {"type":"start-step"}

data: {"type":"tool-input-available","toolCallId":"call_123","toolName":"get_demo_context","input":{"topic":"planning"}}

data: {"type":"tool-output-available","toolCallId":"call_123","output":"Demo context for planning..."}

data: {"type":"finish-step"}

data: {"type":"text-start","id":"text-1"}

data: {"type":"text-delta","id":"text-1","delta":"To help plan your day"}

data: {"type":"text-end","id":"text-1"}

data: {"type":"finish"}

data: [DONE]
```

## Practical Recommendation

Use Vercel AI SDK `useChat` with `DefaultChatTransport` and `prepareSendMessagesRequest` to convert the request body into Relivo's current input contract.
