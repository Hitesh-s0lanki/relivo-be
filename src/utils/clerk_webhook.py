"""
Verification for Clerk (Svix) webhook signatures.

Implemented against the Svix signature scheme with the standard library rather
than pulling in the `svix` package for one HMAC comparison.
"""

import base64
import hashlib
import hmac
import logging
import os
import time

logger = logging.getLogger(__name__)

# Svix rejects timestamps outside a five-minute window to bound replay attacks.
TOLERANCE_SECONDS = 5 * 60

SECRET_ENV_VAR = "CLERK_WEBHOOK_SECRET"
SECRET_PREFIX = "whsec_"


class ClerkWebhookSecretMissingError(Exception):
    """Raised when CLERK_WEBHOOK_SECRET is not configured."""


class ClerkWebhookSignatureError(Exception):
    """Raised when a webhook signature does not verify."""


def verify_clerk_webhook(
    *,
    body: bytes,
    svix_id: str | None,
    svix_timestamp: str | None,
    svix_signature: str | None,
    secret: str | None = None,
) -> None:
    """Verify a Clerk webhook, raising when it cannot be trusted."""
    resolved = secret if secret is not None else os.getenv(SECRET_ENV_VAR, "")
    if not resolved:
        raise ClerkWebhookSecretMissingError(SECRET_ENV_VAR)

    if not svix_id or not svix_timestamp or not svix_signature:
        raise ClerkWebhookSignatureError("missing svix headers")

    _assert_fresh(svix_timestamp)

    expected = _sign(resolved, f"{svix_id}.{svix_timestamp}.".encode() + body)
    provided = _parse_signatures(svix_signature)

    if not any(hmac.compare_digest(expected, candidate) for candidate in provided):
        raise ClerkWebhookSignatureError("signature mismatch")


def _sign(secret: str, signed_content: bytes) -> str:
    """Return the base64 HMAC-SHA256 of the signed content."""
    key = secret[len(SECRET_PREFIX) :] if secret.startswith(SECRET_PREFIX) else secret

    try:
        secret_bytes = base64.b64decode(key)
    except (ValueError, TypeError) as exc:
        raise ClerkWebhookSignatureError("malformed webhook secret") from exc

    digest = hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _parse_signatures(header: str) -> list[str]:
    """Extract the v1 signatures from a space-separated svix-signature header."""
    signatures = []
    for part in header.split():
        version, _, signature = part.partition(",")
        if version == "v1" and signature:
            signatures.append(signature)
    return signatures


def _assert_fresh(svix_timestamp: str) -> None:
    """Reject timestamps far enough from now to indicate a replay."""
    try:
        sent_at = int(svix_timestamp)
    except ValueError as exc:
        raise ClerkWebhookSignatureError("invalid svix-timestamp") from exc

    if abs(time.time() - sent_at) > TOLERANCE_SECONDS:
        raise ClerkWebhookSignatureError("svix-timestamp outside tolerance")
