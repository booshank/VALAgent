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

    def test_explicit_save_filter_and_delete(self) -> None:
        self.store.ensure_persona("analyst-2", "Analyst Two")
        conv = self.store.ensure_conversation(None, "analyst-2")
        # Older auto search that should still match a topic filter.
        for idx in range(12):
            self.store.save_search(
                "analyst-2",
                f"Show contracts for Vendor-{idx}",
                conversation_id=conv["id"],
                mark_saved=False,
            )
        pinned = self.store.save_search(
            "analyst-2",
            "Compare IBM and Salesforce",
            conversation_id=conv["id"],
            result_preview="unavailable",
            mark_saved=True,
        )
        self.assertTrue(pinned.get("saved"))

        filtered = self.store.list_searches("analyst-2", query="Vendor-0", limit=5)
        self.assertEqual(len(filtered), 1)
        self.assertIn("Vendor-0", filtered[0]["query"])

        pinned_only = self.store.list_searches("analyst-2", saved_only=True)
        self.assertEqual(len(pinned_only), 1)
        self.assertEqual(pinned_only[0]["id"], pinned["id"])

        recalled = self.store.recall("analyst-2", query="IBM", limit=5)
        self.assertEqual(len(recalled["searches"]), 1)

        self.assertTrue(self.store.delete_search(int(pinned["id"]), persona_id="analyst-2"))
        self.assertEqual(self.store.list_searches("analyst-2", saved_only=True), [])

    def test_is_search_like(self) -> None:
        self.assertTrue(is_search_like("Compare CON-0001 and CON-0002"))
        self.assertTrue(is_search_like("Retrieve my searches"))
        self.assertFalse(is_search_like("Thanks!"))


if __name__ == "__main__":
    unittest.main()
