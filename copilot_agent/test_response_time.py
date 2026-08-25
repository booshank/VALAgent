"""Unit tests for query response-time footer helpers."""

from __future__ import annotations

from response_time import append_response_time, format_elapsed, strip_response_time


def test_format_elapsed_ms() -> None:
    assert format_elapsed(0.42) == "420 ms"
    assert format_elapsed(0) == "0 ms"


def test_format_elapsed_seconds() -> None:
    assert format_elapsed(1.234) == "1.23 s"
    assert format_elapsed(12.34) == "12.3 s"


def test_append_response_time() -> None:
    out = append_response_time("Hello contracts", 1.5)
    assert out.startswith("Hello contracts")
    assert "---" in out
    assert "Response time: 1.50 s" in out


def test_append_response_time_idempotent() -> None:
    once = append_response_time("Body", 0.5)
    twice = append_response_time(once, 9.0)
    assert twice == once
    assert twice.count("Response time:") == 1


def test_strip_response_time() -> None:
    with_footer = append_response_time("Compare result table", 2.0)
    assert strip_response_time(with_footer) == "Compare result table"
    assert strip_response_time("plain reply") == "plain reply"


if __name__ == "__main__":
    test_format_elapsed_ms()
    test_format_elapsed_seconds()
    test_append_response_time()
    test_append_response_time_idempotent()
    test_strip_response_time()
    print("test_response_time: ok")
