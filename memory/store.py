"""
Persistent persona / conversation / search memory for VAL CoPilot.

SQLite-backed store shared by the Streamlit Validation UI and the Cognitive
Routing Agent. Default path: <repo>/data/persona_memory.sqlite
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _REPO_ROOT / "data" / "persona_memory.sqlite"

_SEARCH_LIKE_RE = re.compile(
    r"\b("
    r"search|find|show|list|compare|expir\w*|overlap\w*|risk|profile|"
    r"contract|vendor|supplier|renewal|missing|spend|retrieve|recall|history"
    r")\b",
    re.I,
)


def default_db_path() -> Path:
    override = (os.getenv("VAL_MEMORY_DB") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _DEFAULT_DB


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_search_like(text: str) -> bool:
    return bool(_SEARCH_LIKE_RE.search(text or ""))


class PersonaMemoryStore:
    """SQLite persistence for personas, conversations, messages, and searches."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS personas (
                    id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    persona_id TEXT NOT NULL,
                    title TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (persona_id) REFERENCES personas(id)
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    meta_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                );
                CREATE TABLE IF NOT EXISTS searches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    persona_id TEXT NOT NULL,
                    conversation_id TEXT,
                    query TEXT NOT NULL,
                    result_preview TEXT,
                    created_at TEXT NOT NULL,
                    saved INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (persona_id) REFERENCES personas(id)
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_persona
                    ON conversations(persona_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                    ON messages(conversation_id, id ASC);
                CREATE INDEX IF NOT EXISTS idx_searches_persona
                    ON searches(persona_id, created_at DESC);
                """
            )
            # Lightweight migration for DBs created before the `saved` column.
            cols = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(searches)").fetchall()
            }
            if "saved" not in cols:
                conn.execute(
                    "ALTER TABLE searches ADD COLUMN saved INTEGER NOT NULL DEFAULT 0"
                )

    def ensure_persona(self, persona_id: str, display_name: str | None = None) -> dict[str, Any]:
        persona_id = (persona_id or "").strip() or "default-user"
        name = (display_name or "").strip() or persona_id
        now = utc_now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM personas WHERE id = ?", (persona_id,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE personas SET display_name = ?, updated_at = ? WHERE id = ?",
                    (name, now, persona_id),
                )
            else:
                conn.execute(
                    "INSERT INTO personas (id, display_name, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (persona_id, name, now, now),
                )
            row = conn.execute(
                "SELECT * FROM personas WHERE id = ?", (persona_id,)
            ).fetchone()
        return dict(row)

    def list_personas(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM personas ORDER BY updated_at DESC, display_name ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def ensure_conversation(
        self,
        conversation_id: str | None,
        persona_id: str,
        *,
        title: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_persona(persona_id)
        conversation_id = (conversation_id or "").strip() or str(uuid.uuid4())
        now = utc_now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if row:
                if title:
                    conn.execute(
                        "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                        (title, now, conversation_id),
                    )
                else:
                    conn.execute(
                        "UPDATE conversations SET updated_at = ? WHERE id = ?",
                        (now, conversation_id),
                    )
            else:
                conn.execute(
                    "INSERT INTO conversations "
                    "(id, persona_id, title, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (conversation_id, persona_id, title, now, now),
                )
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        return dict(row)

    def list_conversations(self, persona_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT c.*, "
                "(SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) "
                "AS message_count, "
                "(SELECT content FROM messages m WHERE m.conversation_id = c.id "
                " AND m.role = 'user' ORDER BY m.id ASC LIMIT 1) AS first_user_message "
                "FROM conversations c "
                "WHERE c.persona_id = ? "
                "ORDER BY c.updated_at DESC "
                "LIMIT ?",
                (persona_id, max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_conversation(self, conversation_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM searches WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        *,
        meta: dict[str, Any] | None = None,
        persona_id: str | None = None,
        record_search: bool = True,
    ) -> dict[str, Any]:
        now = utc_now()
        meta_json = json.dumps(meta, default=str) if meta is not None else None
        with self._connect() as conn:
            conv = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if not conv:
                if not persona_id:
                    raise ValueError(
                        f"Unknown conversation {conversation_id}; provide persona_id to create it"
                    )
                self.ensure_conversation(conversation_id, persona_id)
            else:
                persona_id = str(conv["persona_id"])
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now, conversation_id),
                )
                # Auto-title from first user message.
                if role == "user" and not conv["title"]:
                    title = (content or "").strip().replace("\n", " ")[:80] or None
                    if title:
                        conn.execute(
                            "UPDATE conversations SET title = ? WHERE id = ?",
                            (title, conversation_id),
                        )

            cur = conn.execute(
                "INSERT INTO messages "
                "(conversation_id, role, content, meta_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (conversation_id, role, content, meta_json, now),
            )
            message_id = int(cur.lastrowid)

            if record_search and role == "user" and is_search_like(content):
                conn.execute(
                    "INSERT INTO searches "
                    "(persona_id, conversation_id, query, result_preview, created_at, saved) "
                    "VALUES (?, ?, ?, ?, ?, 0)",
                    (persona_id, conversation_id, content.strip(), None, now),
                )

        return {
            "id": message_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "meta": meta,
            "created_at": now,
        }

    def save_search(
        self,
        persona_id: str,
        query: str,
        *,
        conversation_id: str | None = None,
        result_preview: str | None = None,
        mark_saved: bool = True,
    ) -> dict[str, Any]:
        """Explicitly persist a search so it can be retrieved later."""
        persona_id = (persona_id or "").strip() or "default-user"
        query = (query or "").strip()
        if not query:
            raise ValueError("query is required to save a search")
        self.ensure_persona(persona_id)
        if conversation_id:
            self.ensure_conversation(conversation_id, persona_id)
        now = utc_now()
        preview = None
        if result_preview:
            preview = result_preview.strip().replace("\n", " ")[:240]
        with self._connect() as conn:
            # Prefer updating an identical recent auto-saved row instead of duping.
            existing = conn.execute(
                "SELECT id FROM searches "
                "WHERE persona_id = ? AND query = ? "
                "ORDER BY id DESC LIMIT 1",
                (persona_id, query),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE searches SET "
                    "result_preview = COALESCE(?, result_preview), "
                    "conversation_id = COALESCE(?, conversation_id), "
                    "saved = ?, created_at = ? "
                    "WHERE id = ?",
                    (
                        preview,
                        conversation_id,
                        1 if mark_saved else 0,
                        now,
                        int(existing["id"]),
                    ),
                )
                search_id = int(existing["id"])
            else:
                cur = conn.execute(
                    "INSERT INTO searches "
                    "(persona_id, conversation_id, query, result_preview, created_at, saved) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        persona_id,
                        conversation_id,
                        query,
                        preview,
                        now,
                        1 if mark_saved else 0,
                    ),
                )
                search_id = int(cur.lastrowid)
            row = conn.execute(
                "SELECT * FROM searches WHERE id = ?", (search_id,)
            ).fetchone()
        return dict(row)

    def delete_search(self, search_id: int, *, persona_id: str | None = None) -> bool:
        with self._connect() as conn:
            if persona_id:
                cur = conn.execute(
                    "DELETE FROM searches WHERE id = ? AND persona_id = ?",
                    (int(search_id), persona_id),
                )
            else:
                cur = conn.execute(
                    "DELETE FROM searches WHERE id = ?", (int(search_id),)
                )
            return cur.rowcount > 0

    def get_search(self, search_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM searches WHERE id = ?", (int(search_id),)
            ).fetchone()
        return dict(row) if row else None

    def update_latest_search_preview(
        self,
        persona_id: str,
        conversation_id: str,
        preview: str,
    ) -> None:
        preview = (preview or "").strip().replace("\n", " ")[:240]
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM searches "
                "WHERE persona_id = ? AND conversation_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (persona_id, conversation_id),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE searches SET result_preview = ? WHERE id = ?",
                    (preview, int(row["id"])),
                )

    def get_messages(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC"
        )
        params: list[Any] = [conversation_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw_meta = item.pop("meta_json", None)
            item["meta"] = json.loads(raw_meta) if raw_meta else None
            out.append(item)
        return out

    def chat_history_dicts(
        self,
        conversation_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, str]]:
        """Return recent turns as {role, content} for agent chat_history."""
        messages = self.get_messages(conversation_id)
        if limit and len(messages) > limit:
            messages = messages[-limit:]
        return [
            {"role": str(m["role"]), "content": str(m["content"])}
            for m in messages
            if m.get("role") in {"user", "assistant", "human", "ai"}
        ]

    def list_searches(
        self,
        persona_id: str,
        *,
        limit: int = 50,
        query: str | None = None,
        saved_only: bool = False,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM searches WHERE persona_id = ?"
        params: list[Any] = [persona_id]
        if saved_only:
            sql += " AND saved = 1"
        needle = (query or "").strip()
        if needle:
            sql += " AND (LOWER(query) LIKE ? OR LOWER(COALESCE(result_preview, '')) LIKE ?)"
            like = f"%{needle.lower()}%"
            params.extend([like, like])
        sql += " ORDER BY saved DESC, created_at DESC, id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def recall(
        self,
        persona_id: str,
        *,
        query: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Retrieve prior searches + recent conversations for a persona."""
        # Search filter runs in SQL so older matching queries are not missed.
        searches = self.list_searches(
            persona_id,
            limit=max(1, int(limit)),
            query=query,
        )
        conversations = self.list_conversations(persona_id, limit=max(25, int(limit)))
        needle = (query or "").strip().lower()
        if needle:
            conversations = [
                row
                for row in conversations
                if needle in str(row.get("title") or "").lower()
                or needle in str(row.get("first_user_message") or "").lower()
            ]
        return {
            "persona_id": persona_id,
            "query": query,
            "searches": searches[:limit],
            "conversations": conversations[:limit],
        }


_store: PersonaMemoryStore | None = None
_store_path: str | None = None


def get_memory_store(db_path: Path | str | None = None) -> PersonaMemoryStore:
    global _store, _store_path
    if db_path is not None:
        return PersonaMemoryStore(db_path)
    path = str(default_db_path())
    if _store is None or _store_path != path:
        _store = PersonaMemoryStore(path)
        _store_path = path
    return _store
