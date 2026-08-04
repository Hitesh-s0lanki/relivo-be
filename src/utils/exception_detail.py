"""Readable one-line descriptions for exceptions, including exception groups."""

MAX_LEAVES = 5


def describe_exception(exc: BaseException) -> str:
    """
    Flatten an exception into one readable line.

    Every MCP transport runs inside an `anyio` task group, so a refused
    connection arrives as `unhandled errors in a TaskGroup (1 sub-exception)`
    — a message that hides the 401, DNS failure, or timeout that actually
    stopped it. Unwrapping the group is what puts the real reason in front of
    the user instead of a description of our own concurrency.
    """
    messages: list[str] = []

    for leaf in _leaves(exc):
        text = " ".join(str(leaf).split()) or type(leaf).__name__
        if text not in messages:
            messages.append(text)

    if not messages:
        return type(exc).__name__

    shown = messages[:MAX_LEAVES]
    remaining = len(messages) - len(shown)
    if remaining:
        shown.append(f"(+{remaining} more)")
    return "; ".join(shown)


def _leaves(exc: BaseException) -> list[BaseException]:
    """Return the innermost exceptions of a possibly nested exception group."""
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for sub in exc.exceptions for leaf in _leaves(sub)]
    return [exc]
