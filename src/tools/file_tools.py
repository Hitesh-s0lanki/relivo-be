"""Tools for reading uploaded chat files by durable reference."""

from io import BytesIO
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from src.database import get_sessionmaker
from src.models import UserFile
from src.services.user_file_service import (
    S3StorageError,
    UserFileNotFoundError,
    UserFileObjectNotFoundError,
    UserFileService,
)

DEFAULT_FILE_READ_CHARS = 40_000
MAX_FILE_READ_CHARS = 80_000
TEXT_CACHE_MAX_ENTRIES = 64
TEXT_LIKE_CONTENT_TYPES = {
    "application/json",
    "application/xml",
    "text/csv",
    "text/markdown",
    "text/plain",
    "text/xml",
}
TEXT_LIKE_EXTENSIONS = {".csv", ".json", ".md", ".txt", ".xml"}
_TEXT_CACHE: dict[str, str] = {}


class UnsupportedFileReadError(Exception):
    """Raised when an uploaded file cannot be extracted by this tool."""


@tool
async def read_uploaded_file(
    provider_file_id: str,
    cursor: int = 0,
    max_chars: int = DEFAULT_FILE_READ_CHARS,
) -> dict[str, Any]:
    """Read an uploaded PDF or text file by providerFileId with cursor pagination."""
    file_id = str(provider_file_id or "").strip()
    if not file_id:
        return _tool_error("invalid_file_ref", "provider_file_id is required")

    cursor, max_chars = _normalize_page_request(cursor, max_chars)

    try:
        async with get_sessionmaker()() as session:
            service = UserFileService(session)
            metadata, contents = await service.read_file_bytes(file_id)
    except UserFileNotFoundError:
        return _tool_error("file_not_found", "Uploaded file metadata was not found")
    except UserFileObjectNotFoundError:
        return _tool_error("file_object_not_found", "Uploaded file content is missing from storage")
    except S3StorageError:
        return _tool_error("file_storage_error", "Uploaded file could not be read from storage")

    try:
        text = _cached_file_text(metadata, contents)
    except UnsupportedFileReadError as exc:
        return _tool_error("unsupported_file_type", str(exc), metadata)
    except PdfReadError:
        return _tool_error("pdf_read_error", "PDF could not be parsed", metadata)

    if not text.strip():
        return {
            "success": False,
            "error": "empty_extracted_text",
            "message": (
                "No selectable text was extracted. This may be a scanned or image-only PDF; "
                "OCR is not available in this tool."
            ),
            "file": _file_summary(metadata),
        }

    page = _slice_text(text, cursor, max_chars)
    return {
        "success": True,
        "file": _file_summary(metadata),
        **page,
    }


def _cached_file_text(metadata: UserFile, contents: bytes) -> str:
    cache_key = f"{metadata.id}:{metadata.checksum_sha256}"
    cached = _TEXT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    text = _extract_file_text(metadata.original_filename, metadata.content_type, contents)
    if len(_TEXT_CACHE) >= TEXT_CACHE_MAX_ENTRIES:
        _TEXT_CACHE.clear()
    _TEXT_CACHE[cache_key] = text
    return text


def _extract_file_text(filename: str, content_type: str | None, contents: bytes) -> str:
    media_type = _normalize_content_type(content_type)
    extension = Path(filename).suffix.lower()

    if media_type == "application/pdf" or extension == ".pdf":
        return _extract_pdf_text(contents)

    if media_type.startswith("text/") or media_type in TEXT_LIKE_CONTENT_TYPES:
        return contents.decode("utf-8", errors="replace")

    if extension in TEXT_LIKE_EXTENSIONS:
        return contents.decode("utf-8", errors="replace")

    raise UnsupportedFileReadError(
        f"{media_type or extension or 'file'} is not readable as PDF or plain text"
    )


def _extract_pdf_text(contents: bytes) -> str:
    reader = PdfReader(BytesIO(contents))
    parts: list[str] = []
    for page_index, page in enumerate(reader.pages, start=1):
        parts.append(f"--- Page {page_index} ---")
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _slice_text(text: str, cursor: int, max_chars: int) -> dict[str, Any]:
    start = min(cursor, len(text))
    end = min(start + max_chars, len(text))
    next_cursor = end if end < len(text) else None
    return {
        "content": text[start:end],
        "cursor": start,
        "next_cursor": next_cursor,
        "truncated": next_cursor is not None,
        "total_chars": len(text),
    }


def _normalize_page_request(cursor: int, max_chars: int) -> tuple[int, int]:
    return max(0, int(cursor or 0)), min(
        max(1, int(max_chars or DEFAULT_FILE_READ_CHARS)),
        MAX_FILE_READ_CHARS,
    )


def _normalize_content_type(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def _tool_error(
    error: str,
    message: str,
    metadata: UserFile | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": False,
        "error": error,
        "message": message,
    }
    if metadata is not None:
        payload["file"] = _file_summary(metadata)
    return payload


def _file_summary(metadata: UserFile) -> dict[str, Any]:
    return {
        "provider_file_id": metadata.id,
        "title": metadata.original_filename,
        "media_type": metadata.content_type or "application/octet-stream",
        "size": metadata.size_bytes,
    }
