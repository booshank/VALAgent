"""Streamlit AppTest harness for the Validation UI against a mock /api/messages."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import requests
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent
MOCK_SCRIPT = ROOT / "mock_messages_server.py"
APP_SCRIPT = ROOT / "app.py"


def _wait_healthy(timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            resp = requests.get("http://127.0.0.1:3978/health", timeout=1)
            if resp.status_code == 200:
                return
        except requests.RequestException as exc:
            last_err = exc
        time.sleep(0.2)
    raise RuntimeError(f"Mock messages server did not become healthy: {last_err}")


def test_streamlit_chat_roundtrip() -> None:
    proc = subprocess.Popen(
        [sys.executable, str(MOCK_SCRIPT)],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_healthy()

        from app import _build_activity, _post_message

        activity = _build_activity("schema check", "conv-app-test")
        assert activity["channelId"] == "emulator"
        assert activity["activityId"]
        assert activity["conversationId"] == "conv-app-test"

        posted = _post_message(
            "http://127.0.0.1:3978/api/messages",
            "hello from helper",
            "conv-app-test",
        )
        assert posted["status_code"] == 200
        assert posted["request"]["channelId"] == "emulator"
        assert "Echo: hello from helper" in posted["response"]["text"]

        at = AppTest.from_file(str(APP_SCRIPT), default_timeout=30)
        at.run()
        assert not at.exception

        assert at.title[0].value == "VAL CoPilot — Validation UI"
        assert "3978" in at.sidebar.text_input[0].value
        assert "messages" in at.session_state
        assert at.session_state["messages"] == []

        at.chat_input[0].set_value("What is vendor spend last quarter?").run()
        assert not at.exception

        messages = at.session_state["messages"]
        assert len(messages) >= 2, messages
        assert messages[0]["role"] == "user"
        assert "vendor spend" in messages[0]["content"]
        assert messages[1]["role"] == "assistant"
        assert "Echo:" in messages[1]["content"]
        assert messages[1]["meta"]["request"]["channelId"] == "emulator"
        assert messages[1]["meta"]["request"]["activityId"]
        assert len(at.chat_message) >= 2
        assert at.chat_message[0].name == "user"
        assert at.chat_message[1].name == "assistant"

        print("test_streamlit_chat_roundtrip passed")
        print(f"  assistant reply: {messages[1]['content']}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    test_streamlit_chat_roundtrip()
