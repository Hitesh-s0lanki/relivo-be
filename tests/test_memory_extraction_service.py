"""Tests for memory extraction helpers."""

from src.services.memory_extraction_service import content_to_text, parse_extraction_result


def test_parse_extraction_result_reads_json_fence() -> None:
    """Extractor parsing should accept common fenced JSON responses."""
    result = parse_extraction_result(
        """```json
        {
          "memories": [
            {
              "type": "preferences",
              "summary": "User prefers concise answers.",
              "tags": ["style"],
              "confidence": 0.91
            }
          ]
        }
        ```"""
    )

    assert len(result.memories) == 1
    assert result.memories[0].type == "preferences"
    assert result.memories[0].confidence == 0.91


def test_parse_extraction_result_returns_empty_on_invalid_json() -> None:
    """Invalid extractor output should fail closed."""
    result = parse_extraction_result("not json")

    assert result.memories == []


def test_content_to_text_reads_model_text_blocks() -> None:
    """Extractor should normalize structured model content before JSON parsing."""
    content = [
        {
            "type": "text",
            "text": '{"memories":[{"type":"info","summary":"User shared a background summary."}]}',
        }
    ]

    assert content_to_text(content).startswith('{"memories"')
