"""Offline structural checks for the Bot Framework mock contract."""

from __future__ import annotations

from app import _build_activity


def test_bot_framework_mock_schema() -> None:
    activity = _build_activity("ping", "conv-validate-1")
    assert activity["type"] == "message"
    assert activity["channelId"] == "emulator"
    assert activity["activityId"]
    assert activity["conversationId"] == "conv-validate-1"
    assert activity["conversation"]["id"] == "conv-validate-1"
    assert activity["text"] == "ping"
    assert activity["from"]["id"]
    assert activity["recipient"]["id"]


if __name__ == "__main__":
    test_bot_framework_mock_schema()
    print("test_bot_framework_mock_schema passed")
