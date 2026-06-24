"""Simple tools available to the chat agent."""

from langchain_core.tools import tool


@tool
def get_demo_context(topic: str) -> str:
    """Return demo context for a topic."""
    return (
        f"Demo context for {topic}: stream model tokens, tool calls, tool results, "
        "agent step updates, and terminal errors as separate events."
    )
