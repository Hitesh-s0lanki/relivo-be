# User API

> **Status: specification.** The `users` table and the `User` model exist
> (`migrations/0004_create_users.sql`, `src/models/user.py`). The routes described here are not
> implemented yet. This document is the contract to build against.

The user API stores the Clerk-backed user profile: identity fields mirrored from Clerk, plus
app-owned profile and preference fields that Clerk does not hold.

`user_id` is the **Clerk user id** (`user_2abc...`). There is no separate UUID. The same value is
already used as `user_id` on `conversations`, `user_files`, and `memories`, so those records join
directly to this table.

## Data Model

User:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Clerk user id. Primary key. Max 200 chars. |
| `external_id` | string/null | Clerk `external_id`, when the app sets one. |
| `email` | string/null | Primary email address. |
| `email_verified` | boolean | Whether the primary email is verified in Clerk. |
| `phone_number` | string/null | Primary phone number. |
| `username` | string/null | Clerk username. |
| `first_name` | string/null | Clerk first name. |
| `last_name` | string/null | Clerk last name. |
| `full_name` | string/null | Display name. |
| `image_url` | string/null | Clerk avatar URL. |
| `has_image` | boolean | Whether the user uploaded an avatar. |
| `work_function` | string/null | App-owned. See allowed values below. |
| `job_title` | string/null | App-owned free text. |
| `company_name` | string/null | App-owned free text. |
| `industry` | string/null | App-owned free text. |
| `team_size` | string/null | App-owned bucket, e.g. `1`, `2-10`, `11-50`, `51-200`, `200+`. |
| `timezone` | string/null | IANA zone, e.g. `Asia/Kolkata`. |
| `locale` | string/null | BCP-47 tag, e.g. `en-US`. |
| `onboarding_completed` | boolean | Whether onboarding was finished. |
| `preferences` | object | App-owned preference bag. Defaults to `{}`. |
| `public_metadata` | object | Mirror of Clerk `public_metadata`. |
| `private_metadata` | object | Mirror of Clerk `private_metadata`. Never returned to clients. |
| `unsafe_metadata` | object | Mirror of Clerk `unsafe_metadata`. |
| `password_enabled` | boolean | Clerk auth flag. |
| `two_factor_enabled` | boolean | Clerk auth flag. |
| `banned` | boolean | Clerk account state. |
| `locked` | boolean | Clerk account state. |
| `last_sign_in_at` | datetime/null | From Clerk. |
| `last_active_at` | datetime/null | From Clerk. |
| `clerk_created_at` | datetime/null | When Clerk created the user. |
| `clerk_updated_at` | datetime/null | When Clerk last updated the user. |
| `created_at` | datetime | When this row was created locally. |
| `updated_at` | datetime | When this row was last updated locally. |

`work_function` suggested values: `engineering`, `product`, `design`, `data`, `marketing`,
`sales`, `finance`, `operations`, `hr`, `legal`, `founder`, `student`, `other`.

Field ownership matters for sync. **Clerk-owned** fields (identity, metadata, auth flags, Clerk
timestamps) are overwritten on every sync. **App-owned** fields (`work_function`, `job_title`,
`company_name`, `industry`, `team_size`, `timezone`, `locale`, `onboarding_completed`,
`preferences`) are only changed by explicit `PATCH` calls and survive a re-sync.

`private_metadata` is omitted from every response body.

## User CRUD

### List Users

```http
GET /users
```

Optional query params:

| Param | Type | Description |
|-------|------|-------------|
| `work_function` | string | Filter by work function. |
| `onboarding_completed` | boolean | Filter by onboarding state. |
| `limit` | integer | Page size. Default `50`, max `200`. |
| `offset` | integer | Rows to skip. Default `0`. |

Returns:

```json
[
  {
    "id": "user_2abc123",
    "email": "hitesh@example.com",
    "full_name": "Hitesh Solanki",
    "work_function": "engineering",
    "job_title": "Backend Engineer",
    "onboarding_completed": true,
    "created_at": "2026-08-03T10:00:00Z",
    "updated_at": "2026-08-03T10:00:00Z"
  }
]
```

### Create User

```http
POST /users
```

`id` is required and must be the Clerk user id. The server does not generate it.

Body:

```json
{
  "id": "user_2abc123",
  "email": "hitesh@example.com",
  "first_name": "Hitesh",
  "last_name": "Solanki",
  "full_name": "Hitesh Solanki",
  "image_url": "https://img.clerk.com/abc.png",
  "work_function": "engineering",
  "job_title": "Backend Engineer",
  "company_name": "Relivo",
  "timezone": "Asia/Kolkata",
  "preferences": {
    "response_style": "concise",
    "default_model": "claude-opus-5"
  }
}
```

Returns `201 Created` with the full user object.

Returns `409 Conflict` when the id already exists. Use `PUT /users/{user_id}` for idempotent
upsert instead.

### Get User

```http
GET /users/{user_id}
```

`user_id` is the Clerk user id.

Returns:

```json
{
  "id": "user_2abc123",
  "external_id": null,
  "email": "hitesh@example.com",
  "email_verified": true,
  "phone_number": null,
  "username": "hitesh",
  "first_name": "Hitesh",
  "last_name": "Solanki",
  "full_name": "Hitesh Solanki",
  "image_url": "https://img.clerk.com/abc.png",
  "has_image": true,
  "work_function": "engineering",
  "job_title": "Backend Engineer",
  "company_name": "Relivo",
  "industry": "software",
  "team_size": "2-10",
  "timezone": "Asia/Kolkata",
  "locale": "en-US",
  "onboarding_completed": true,
  "preferences": {
    "response_style": "concise",
    "default_model": "claude-opus-5"
  },
  "public_metadata": {},
  "unsafe_metadata": {},
  "password_enabled": true,
  "two_factor_enabled": false,
  "banned": false,
  "locked": false,
  "last_sign_in_at": "2026-08-03T09:12:00Z",
  "last_active_at": "2026-08-03T09:40:00Z",
  "clerk_created_at": "2026-06-01T08:00:00Z",
  "clerk_updated_at": "2026-08-03T09:12:00Z",
  "created_at": "2026-06-01T08:00:05Z",
  "updated_at": "2026-08-03T09:12:03Z"
}
```

### Upsert User

```http
PUT /users/{user_id}
```

Idempotent. Creates the row when missing, updates it otherwise. Use this from the frontend on
first authenticated load so a user row always exists before chat, files, or memories are written.

Body is the same shape as `POST /users` minus `id`, which comes from the path.

Returns `200 OK` with the full user object.

### Update User

```http
PATCH /users/{user_id}
```

Partial update. Only the supplied fields change. Omitted fields are untouched; explicit `null`
clears a nullable field.

Body:

```json
{
  "work_function": "product",
  "job_title": "Product Engineer",
  "onboarding_completed": true
}
```

Returns the full user object.

### Delete User

```http
DELETE /users/{user_id}
```

Returns `204 No Content`.

Deleting a user row does **not** cascade to `conversations`, `user_files`, or `memories` — those
tables have no foreign key to `users`. Delete or anonymize them separately if required.

## Preferences

`preferences` is a free-form JSON object owned by the app. Suggested keys:

| Key | Type | Description |
|-----|------|-------------|
| `response_style` | string | e.g. `concise`, `detailed`. |
| `default_model` | string | Preferred model id. |
| `language` | string | Preferred response language. |
| `theme` | string | UI theme. |
| `notifications` | object | Per-channel notification toggles. |

### Get Preferences

```http
GET /users/{user_id}/preferences
```

Returns:

```json
{
  "response_style": "concise",
  "default_model": "claude-opus-5",
  "notifications": {
    "email": true,
    "push": false
  }
}
```

### Merge Preferences

```http
PATCH /users/{user_id}/preferences
```

Shallow merge into the existing object. Top-level keys in the body replace their counterparts;
untouched top-level keys are preserved. Send `null` as a key's value to remove it.

Body:

```json
{
  "response_style": "detailed",
  "theme": null
}
```

Returns the merged preferences object.

### Replace Preferences

```http
PUT /users/{user_id}/preferences
```

Replaces the entire object. Send `{}` to clear it.

## Clerk Sync

### Sync From Clerk Webhook

```http
POST /users/clerk/webhook
```

Handles `user.created`, `user.updated`, and `user.deleted` events. Accepts the raw Clerk webhook
payload and verifies the Svix signature headers.

Required headers:

| Header | Description |
|--------|-------------|
| `svix-id` | Webhook message id. |
| `svix-timestamp` | Webhook timestamp. |
| `svix-signature` | Webhook signature, verified against `CLERK_WEBHOOK_SECRET`. |

Behaviour by event:

| Event | Effect |
|-------|--------|
| `user.created` | Insert the row. App-owned fields take their defaults. |
| `user.updated` | Update Clerk-owned fields only. App-owned fields are preserved. |
| `user.deleted` | Delete the row. Related conversations, files, and memories are left intact. |

Returns `200 OK` with:

```json
{
  "received": true,
  "event": "user.updated",
  "user_id": "user_2abc123"
}
```

Returns `400 Bad Request` on signature verification failure.

Requires `CLERK_WEBHOOK_SECRET` in the environment. It is not in `.env.example` yet.

## Errors

Missing user:

```json
{
  "status": 404,
  "message": "user not found",
  "error_tag": "user_not_found"
}
```

Duplicate user on create:

```json
{
  "status": 409,
  "message": "user already exists",
  "error_tag": "user_already_exists"
}
```

Invalid webhook signature:

```json
{
  "status": 400,
  "message": "invalid clerk webhook signature",
  "error_tag": "clerk_webhook_invalid_signature"
}
```
