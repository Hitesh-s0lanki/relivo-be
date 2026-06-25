# Upload API

`POST /ai/uploads` uploads chat attachments through the existing S3-backed user file service.

The endpoint is intended for frontend chat flows:

1. Upload selected files with multipart form data.
2. Use the returned `attachments` in `POST /chat`.
3. Persist the same `attachments` on conversation messages.

## Endpoint

```http
POST /ai/uploads
```

## Request

Headers:

| Header | Value |
|--------|-------|
| `Content-Type` | `multipart/form-data` |

Form fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `files[]` | file[] | Yes | One or more files to upload to S3. |
| `userId` | string | Required unless `conversationId` is present | User owner for the uploaded files. |
| `conversationId` | string | Required unless `userId` is present | Existing conversation id. The backend resolves `user_id` from the conversation. |

The same S3 limits used by `POST /files` apply. By default each file can be up to
`AWS_S3_MAX_UPLOAD_MB`, which defaults to `25`.

## Response

```json
{
  "success": true,
  "data": {
    "attachments": [
      {
        "id": "file-id",
        "url": "https://s3-presigned-url.example/screenshot.png",
        "mediaType": "image/png",
        "title": "screenshot.png",
        "size": 123456,
        "providerFileId": "file-id"
      }
    ]
  }
}
```

`url` is a temporary presigned S3 URL for immediate model access and frontend preview.
`id` and `providerFileId` are the durable file references backed by the `user_files` table.
Keep `providerFileId` when sending attachments to `/chat`; the backend uses it to read the
stored S3 object and send image data to the model without relying on the model downloading a
private URL.

## cURL

```bash
curl -X POST http://localhost:8000/ai/uploads \
  -F "conversationId=conversation-id" \
  -F "files[]=@/path/to/screenshot.png" \
  -F "files[]=@/path/to/diagram.png"
```

## Chat Payload

Pass the returned attachment objects into chat:

```json
{
  "user_message": "What is in this image?",
  "thread_id": "conversation-id",
  "stream_mode": ["updates", "messages"],
  "attachments": [
    {
      "url": "https://s3-presigned-url.example/screenshot.png",
      "mediaType": "image/png",
      "title": "screenshot.png",
      "providerFileId": "file-id"
    }
  ]
}
```

## Conversation Persistence

Persist the same attachment references with the user message:

```json
{
  "role": "user",
  "text": "What is in this image?",
  "attachments": [
    {
      "url": "https://s3-presigned-url.example/screenshot.png",
      "mediaType": "image/png",
      "title": "screenshot.png",
      "providerFileId": "file-id"
    }
  ]
}
```
