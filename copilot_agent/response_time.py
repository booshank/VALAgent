"""Helpers for appending query response-time footers to conversation replies."""

from __future__ import annotations

_RESPONSE_TIME_MARKER = "Response time:"


def format_elapsed(seconds: float) -> str:
    """Human-readable elapsed duration for reply footers."""
    if seconds < 0:
        seconds = 0.0
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 10:
        return f"{seconds:.2f} s"
    return f"{seconds:.1f} s"


def append_response_time(answer: str, elapsed_seconds: float) -> str:
    """Append a response-time footer to an assistant reply (idempotent)."""
    text = str(answer or "").rstrip()
    if _RESPONSE_TIME_MARKER.lower() in text.lower():
        return text
    label = format_elapsed(elapsed_seconds)
    if not text:
        return f"{_RESPONSE_TIME_MARKER} {label}"
    return f"{text}\n\n---\n{_RESPONSE_TIME_MARKER} {label}"


def strip_response_time(answer: str) -> str:
    """Remove a trailing response-time footer so it is not fed back as history."""
    text = str(answer or "").rstrip()
    marker = f"\n---\n{_RESPONSE_TIME_MARKER}"
    idx = text.rfind(marker)
    if idx >= 0:
        return text[:idx].rstrip()
    if text.lower().startswith(_RESPONSE_TIME_MARKER.lower()):
        return ""
    return text
