# relivo-be-server

FastAPI backend server for Relivo.

## Requirements

- Python 3.13
- [uv](https://docs.astral.sh/uv/) package manager

## Setup

```bash
uv sync
```

## Run

Set `ENVIRONMENT=development` or `ENVIRONMENT=production` in `.env`, then run:

```bash
python src/main.py
```

Server runs at `http://localhost:8000`

## Database

Apply the SQL migrations before using conversation or file upload APIs:

```bash
uv run python scripts/apply_migrations.py
```

## Environment Variables

The app loads from a `.env` file or environment variables. All have defaults:

| Variable                           | Default                            | Description                                                                                     |
| ---------------------------------- | ---------------------------------- | ----------------------------------------------------------------------------------------------- |
| `APP_NAME`                         | `relivo-be-server`                 | Application name                                                                                |
| `VERSION`                          | `0.1.0`                            | App version                                                                                     |
| `ENVIRONMENT`                      | `development`                      | Runtime environment                                                                             |
| `HOST`                             | `127.0.0.1`                        | Server host                                                                                     |
| `PORT`                             | `8000`                             | Server port                                                                                     |
| `RELOAD`                           | based on environment               | Override Uvicorn auto-reload toggle                                                             |
| `OPENAI_API_KEY`                   | unset                              | Enables real model streaming when configured                                                    |
| `RELIVO_CHAT_MODEL`                | `gpt-5-mini`                       | Reasoning-capable chat model used when `OPENAI_API_KEY` is set                                  |
| `RELIVO_CHAT_REASONING_EFFORT`     | `low`                              | Reasoning effort for the chat model                                                             |
| `RELIVO_CHAT_USE_RESPONSES_API`    | `true`                             | Uses OpenAI Responses API mode for reasoning models                                             |
| `FIRECRAWL_API_KEY`                | unset                              | Enables authenticated Firecrawl MCP tools for agent web search, scrape, crawl, and parse access |
| `FIRECRAWL_MCP_ENABLED`            | `true`                             | Toggle Firecrawl MCP tool loading for the chat agent                                            |
| `FIRECRAWL_MCP_URL`                | `https://mcp.firecrawl.dev/v2/mcp` | Firecrawl MCP endpoint. Supports `{FIRECRAWL_API_KEY}` in custom URLs                           |
| `AWS_REGION`                       | `us-east-1`                        | Default AWS region for AWS clients                                                              |
| `AWS_ACCESS_KEY_ID`                | unset                              | AWS access key id used by boto3 for S3                                                          |
| `AWS_SECRET_ACCESS_KEY`            | unset                              | AWS secret access key used by boto3 for S3                                                      |
| `AWS_S3_BUCKET`                    | unset                              | S3 bucket used for user file uploads                                                            |
| `AWS_S3_KEY_PREFIX`                | `user-files`                       | S3 key prefix for uploaded files                                                                |
| `AWS_S3_MAX_UPLOAD_MB`             | `25`                               | Maximum uploaded file size in MB                                                                |
| `AWS_S3_PRESIGNED_EXPIRES_SECONDS` | `3600`                             | Lifetime for generated download URLs                                                            |
| `AWS_S3_ENDPOINT_URL`              | unset                              | Optional S3-compatible endpoint URL                                                             |
| `AWS_S3_SERVER_SIDE_ENCRYPTION`    | unset                              | Optional S3 server-side encryption mode                                                         |
| `AWS_S3_KMS_KEY_ID`                | unset                              | Optional KMS key id when using KMS encryption                                                   |

## API

- `POST /chat` — stream an agent response with Server-Sent Events
- `POST /ai/uploads` — upload chat attachments to S3 and return frontend attachment references
- `/conversations` — CRUD for conversations and conversation messages
- `/files` — upload, list, fetch, download, and delete user files stored in S3
- `GET /docs` — Swagger UI
- `GET /redoc` — ReDoc

Open `http://localhost:8000/docs` for the full interactive API documentation.
See `docs/chat_request_api.md` for the chat request API contract.
See `docs/conversation_api.md` for the conversation API contract.
See `docs/upload_api.md` for the chat upload API contract.

File uploads are multipart form requests:

```bash
curl -X POST http://localhost:8000/ai/uploads \
  -F "userId=user-123" \
  -F "files[]=@/path/to/screenshot.png"
```

`/ai/uploads` also accepts `conversationId` instead of `userId`; the backend resolves the
conversation owner before storing files in S3. The response returns `attachments` with
`url`, `mediaType`, `title`, `size`, and `providerFileId`. The `url` is a temporary
presigned S3 URL; keep `providerFileId`/`id` as the durable file reference.
When those attachments are sent to `/chat`, include `providerFileId` so the backend can
read the stored image from S3 and send model-readable image data instead of asking the model
to download a private URL.
To refresh one attachment URL directly from its durable id, call
`GET /ai/uploads/{providerFileId}/presigned-url`.

Presigned URLs are generated for the bucket's actual region. The backend detects that region
from S3, so the app can keep `AWS_REGION=ap-south-1` even if the bucket uses another endpoint.

The lower-level file API remains available:

```bash
curl -X POST http://localhost:8000/files \
  -F "user_id=user-123" \
  -F "file=@/path/to/document.pdf"
```

List a user's files with `GET /files/users/{user_id}` and create a temporary download URL
with `GET /files/{file_id}/download`.

```bash
curl -N -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"user_message":"Hello","thread_id":"user-123"}'
```

## Tests

```bash
uv run pytest tests/ -v
```

## CI/CD

GitHub Actions runs linting, formatting, tests, and a Docker image build for pull requests.
Pushes to `main` or `release` publish the image to GitHub Container Registry:

```text
ghcr.io/<owner>/<repo>:sha-<commit-sha>
ghcr.io/<owner>/<repo>:main
ghcr.io/<owner>/<repo>:release
ghcr.io/<owner>/<repo>:latest  # main only
ghcr.io/<owner>/<repo>:prod    # release only
```

For Render image deploys, add a repository secret named `RENDER_DEPLOY_HOOK_URL` after the
Render service exists. Until that secret is present, the workflow still builds and pushes the
image, then skips the Render deploy step and prints the deployable image tag in the Actions
summary.
