"""Tests for uploaded file reader helpers."""

from io import BytesIO

from pypdf import PdfWriter

from src.tools.file_tools import (
    MAX_FILE_READ_CHARS,
    _extract_file_text,
    _normalize_page_request,
    _slice_text,
)


def test_extract_file_text_reads_pdf_page_markers() -> None:
    """PDF extraction should include page markers even when the page has no text."""
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)

    text = _extract_file_text("report.pdf", "application/pdf", output.getvalue())

    assert "--- Page 1 ---" in text


def test_extract_file_text_reads_text_like_files() -> None:
    """Plain text-like uploads should be decoded as UTF-8."""
    text = _extract_file_text("notes.md", "text/markdown; charset=utf-8", b"# Notes")

    assert text == "# Notes"


def test_slice_text_returns_next_cursor() -> None:
    """File reader slices should expose cursor pagination metadata."""
    page = _slice_text("abcdef", cursor=2, max_chars=3)

    assert page == {
        "content": "cde",
        "cursor": 2,
        "next_cursor": 5,
        "truncated": True,
        "total_chars": 6,
    }


def test_normalize_page_request_caps_max_chars() -> None:
    """Tool page requests should clamp negative cursors and oversized chunks."""
    cursor, max_chars = _normalize_page_request(-5, MAX_FILE_READ_CHARS + 1)

    assert cursor == 0
    assert max_chars == MAX_FILE_READ_CHARS
