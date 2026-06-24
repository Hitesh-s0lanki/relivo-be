"""Tests for chat agent tools."""

from src.tools import get_demo_context


def test_get_demo_context_returns_streaming_context() -> None:
    """The demo context tool should expose useful streaming context."""
    result = get_demo_context.invoke({"topic": "planning"})

    assert "planning" in result
    assert "stream model tokens" in result
    assert "agent step updates" in result
