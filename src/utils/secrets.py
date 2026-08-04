"""Symmetric encryption for credentials stored at rest."""

import json
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

SECRET_KEY_ENV = "RELIVO_MCP_SECRET_KEY"
DEFAULT_KEY_ID = "v1"


class SecretKeyMissingError(RuntimeError):
    """Raised when a secret must be stored but no encryption key is configured."""


class SecretDecryptError(RuntimeError):
    """Raised when stored ciphertext cannot be decrypted with the current key."""


def secret_key_configured() -> bool:
    """Return whether an encryption key is available."""
    return bool(os.getenv(SECRET_KEY_ENV, "").strip())


def build_cipher() -> Fernet:
    """Build the Fernet cipher from the configured key."""
    key = os.getenv(SECRET_KEY_ENV, "").strip()
    if not key:
        raise SecretKeyMissingError(
            f"{SECRET_KEY_ENV} is not set; generate one with "
            "`python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'`"
        )
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise SecretKeyMissingError(f"{SECRET_KEY_ENV} is not a valid Fernet key") from exc


def encrypt_text(value: str) -> str:
    """Encrypt a string for storage."""
    return build_cipher().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_text(ciphertext: str) -> str:
    """Decrypt a stored string."""
    try:
        return build_cipher().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretDecryptError("stored credential could not be decrypted") from exc


def encrypt_json(value: Any) -> str:
    """Encrypt a JSON-serializable value for storage."""
    return encrypt_text(json.dumps(value, separators=(",", ":"), sort_keys=True))


def decrypt_json(ciphertext: str) -> Any:
    """Decrypt a stored JSON value."""
    return json.loads(decrypt_text(ciphertext))
