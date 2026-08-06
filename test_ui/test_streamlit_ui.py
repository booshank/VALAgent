"""Streamlit AppTest harness for the Validation UI against a mock /api/messages."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
MOCK_SCRIPT = ROOT / "mock_messages_server.py"
APP_SCRIPT = ROOT / "app.py"
MOCK_PORT = 13978
MOCK_URL = f"http://127.0.0.1:{MOCK_PORT}/api/messages"
MOCK_HEALTH = f"http://127.0.0.1:{MOCK_PORT}/health"


def _wait_healthy(timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            resp = requests.get(MOCK_HEALTH, timeout=1)
            if resp.status_code == 200 and "val-mock-messages" in resp.text:
                return
        except requests.RequestException as exc:
            last_err = exc
        time.sleep(0.2)
    raise RuntimeError(f"Mock messages server did not become healthy: {last_err}")


def test_streamlit_chat_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "ui_memory.sqlite"
        env = {
            **os.environ,
            "MOCK_MESSAGES_PORT": str(MOCK_PORT),
            "VAL_MEMORY_DB": str(db_path),
            "COPILOT_MESSAGES_URL": MOCK_URL,
        }
        proc = subprocess.Popen(
            [sys.executable, str(MOCK_SCRIPT)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            _wait_healthy()

            # Ensure isolated memory + mock endpoint before importing/running the app.
            os.environ["VAL_MEMORY_DB"] = str(db_path)
            os.environ["COPILOT_MESSAGES_URL"] = MOCK_URL

            from app import _build_activity, _post_message

            activity = _build_activity(
                "schema check",
                "conv-app-test",
                persona_id="validation-user",
                persona_name="Validation User",
            )
            assert activity["channelId"] == "emulator"
            assert activity["activityId"]
            assert activity["conversationId"] == "conv-app-test"
            assert activity["from"]["id"] == "validation-user"
            assert activity["channelData"]["personaId"] == "validation-user"

            posted = _post_message(
                MOCK_URL,
                "hello from helper",
                "conv-app-test",
                persona_id="validation-user",
                persona_name="Validation User",
            )
            assert posted["status_code"] == 200
            assert posted["request"]["channelId"] == "emulator"
            assert "Echo: hello from helper" in posted["response"]["text"]

            at = AppTest.from_file(str(APP_SCRIPT), default_timeout=30)
            at.run()
            assert not at.exception

            assert at.title[0].value == "VAL CoPilot — Validation UI"
            endpoint_values = [str(ti.value) for ti in at.sidebar.text_input]
            assert any(str(MOCK_PORT) in v for v in endpoint_values), endpoint_values
            assert "messages" in at.session_state
            assert at.session_state["messages"] == []
            assert at.session_state["persona_id"] == "validation-user"

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
            assert messages[1]["meta"]["request"]["from"]["id"] == "validation-user"
            assert len(at.chat_message) >= 2
            assert at.chat_message[0].name == "user"
            assert at.chat_message[1].name == "assistant"

            # Persistent memory should retain the search for this persona.
            sys.path.insert(0, str(REPO))
            from memory.store import PersonaMemoryStore

            store = PersonaMemoryStore(db_path)
            searches = store.list_searches(at.session_state["persona_id"])
            assert searches, searches
            assert "vendor spend" in searches[0]["query"]

            print("test_streamlit_chat_roundtrip passed")
            print(f"  assistant reply: {messages[1]['content']}")
            print(f"  saved searches: {len(searches)}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    test_streamlit_chat_roundtrip()
