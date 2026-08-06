"""Unit tests for persistent persona / search memory."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from store import PersonaMemoryStore, is_search_like


class PersonaMemoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "test_memory.sqlite"
        self.store = PersonaMemoryStore(self.db)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_persona_conversation_and_search_roundtrip(self) -> None:
        self.store.ensure_persona("analyst-1", "Contract Analyst")
        conv = self.store.ensure_conversation(None, "analyst-1", title=None)
        conv_id = conv["id"]

        self.store.append_message(
            conv_id,
            "user",
            "Show contracts for Microsoft",
            persona_id="analyst-1",
        )
        self.store.append_message(
            conv_id,
            "assistant",
            "Found 33 Microsoft contracts.",
            persona_id="analyst-1",
            record_search=False,
        )
        self.store.update_latest_search_preview(
            "analyst-1",
            conv_id,
            "Found 33 Microsoft contracts.",
        )

        messages = self.store.get_messages(conv_id)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "user")

        searches = self.store.list_searches("analyst-1")
        self.assertEqual(len(searches), 1)
        self.assertIn("Microsoft", searches[0]["query"])
        self.assertIn("33", searches[0]["result_preview"] or "")

        recalled = self.store.recall("analyst-1", query="Microsoft")
        self.assertEqual(len(recalled["searches"]), 1)
        self.assertGreaterEqual(len(recalled["conversations"]), 1)

        history = self.store.chat_history_dicts(conv_id)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[1]["role"], "assistant")

    def test_is_search_like(self) -> None:
        self.assertTrue(is_search_like("Compare CON-0001 and CON-0002"))
        self.assertFalse(is_search_like("Thanks!"))


if __name__ == "__main__":
    unittest.main()
