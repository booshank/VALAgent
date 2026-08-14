"""
Cognitive Routing Agent — Flask ingress for Microsoft Bot Framework activities.

`/api/messages` accepts Bot Framework JSON payloads and runs the LangChain
agent on a dedicated asyncio loop in a background thread to avoid Flask
thread locking / nested-loop deadlocks.

Persists persona conversations in the shared SQLite memory store and feeds
prior turns back into the agent as chat history.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request
from langchain_core.messages import AIMessage, HumanMessage

from agent import run_turn
from config import get

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from memory.store import get_memory_store  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Dedicated loop so Flask worker threads never call asyncio.run() (which would
# block / nest incorrectly under concurrent Bot Framework traffic).
_loop = asyncio.new_event_loop()
_loop_ready = threading.Event()


def _loop_worker() -> None:
    asyncio.set_event_loop(_loop)
    _loop_ready.set()
    _loop.run_forever()


_worker = threading.Thread(target=_loop_worker, name="val-async-loop", daemon=True)
_worker.start()
_loop_ready.wait(timeout=5)


def _submit(coro: Any, timeout: float = 120.0) -> Any:
    """Schedule a coroutine on the shared loop without locking the Flask thread pool."""
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=timeout)


def _activity_id(activity: dict[str, Any]) -> str:
    return (
        activity.get("id")
        or activity.get("activityId")
        or str(uuid.uuid4())
    )


def _conversation_id(activity: dict[str, Any]) -> str:
    conversation = activity.get("conversation") or {}
    if isinstance(conversation, dict) and conversation.get("id"):
        return str(conversation["id"])
    return str(activity.get("conversationId") or "default")


def _persona_from_activity(activity: dict[str, Any]) -> tuple[str, str]:
    channel_data = activity.get("channelData") or {}
    sender = activity.get("from") or {}
    persona_id = (
        (channel_data.get("personaId") if isinstance(channel_data, dict) else None)
        or sender.get("id")
        or "default-user"
    )
    persona_name = (
        (channel_data.get("personaName") if isinstance(channel_data, dict) else None)
        or sender.get("name")
        or str(persona_id)
    )
    return str(persona_id), str(persona_name)


def _history_messages(conversation_id: str) -> list[Any]:
    store = get_memory_store()
    history = store.chat_history_dicts(conversation_id, limit=20)
    messages: list[Any] = []
    for item in history:
        role = str(item.get("role") or "").lower()
        content = str(item.get("content") or "")
        if role in {"user", "human"}:
            messages.append(HumanMessage(content=content))
        elif role in {"assistant", "ai"}:
            messages.append(AIMessage(content=content))
    return messages


def _build_reply(activity: dict[str, Any], text: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "type": "message",
        "id": str(uuid.uuid4()),
        "timestamp": now,
        "channelId": activity.get("channelId") or "emulator",
        "from": activity.get("recipient") or {"id": "val-copilot", "name": "VAL CoPilot"},
        "recipient": activity.get("from") or {"id": "user", "name": "User"},
        "conversation": {"id": _conversation_id(activity)},
        "replyToId": _activity_id(activity),
        "text": text,
        "serviceUrl": activity.get("serviceUrl") or "",
    }


@app.get("/health")
def health() -> Any:
    return jsonify({"status": "ok", "service": "val-copilot-agent"})


@app.get("/api/memory/searches")
def memory_searches() -> Any:
    """List prior searches for a persona (Validation UI / tooling helper)."""
    persona_id = (request.args.get("persona_id") or "default-user").strip()
    limit = int(request.args.get("limit") or 25)
    query = (request.args.get("q") or request.args.get("query") or "").strip() or None
    saved_only = (request.args.get("saved_only") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    store = get_memory_store()
    store.ensure_persona(persona_id)
    return jsonify(
        {
            "persona_id": persona_id,
            "query": query,
            "searches": store.list_searches(
                persona_id,
                limit=limit,
                query=query,
                saved_only=saved_only,
            ),
        }
    )


@app.post("/api/memory/searches")
def memory_save_search() -> Any:
    """Explicitly save a search query for later retrieval."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400
    persona_id = str(body.get("persona_id") or "default-user").strip()
    query = str(body.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400
    conversation_id = body.get("conversation_id")
    result_preview = body.get("result_preview")
    store = get_memory_store()
    saved = store.save_search(
        persona_id,
        query,
        conversation_id=str(conversation_id) if conversation_id else None,
        result_preview=str(result_preview) if result_preview else None,
        mark_saved=True,
    )
    return jsonify({"persona_id": persona_id, "search": saved}), 201


@app.delete("/api/memory/searches/<int:search_id>")
def memory_delete_search(search_id: int) -> Any:
    """Delete one saved/auto-captured search for a persona."""
    persona_id = (request.args.get("persona_id") or "").strip() or None
    store = get_memory_store()
    deleted = store.delete_search(search_id, persona_id=persona_id)
    if not deleted:
        return jsonify({"error": "search not found", "id": search_id}), 404
    return jsonify({"deleted": True, "id": search_id}), 200


@app.get("/api/memory/recall")
def memory_recall() -> Any:
    """Retrieve prior searches (and conversations) for a persona, optionally filtered."""
    persona_id = (request.args.get("persona_id") or "default-user").strip()
    query = (request.args.get("q") or request.args.get("query") or "").strip() or None
    limit = int(request.args.get("limit") or 8)
    store = get_memory_store()
    store.ensure_persona(persona_id)
    return jsonify(store.recall(persona_id, query=query, limit=limit))


@app.get("/api/memory/conversations")
def memory_conversations() -> Any:
    """List prior conversations for a persona."""
    persona_id = (request.args.get("persona_id") or "default-user").strip()
    limit = int(request.args.get("limit") or 25)
    store = get_memory_store()
    store.ensure_persona(persona_id)
    return jsonify(
        {
            "persona_id": persona_id,
            "conversations": store.list_conversations(persona_id, limit=limit),
        }
    )


@app.delete("/api/memory/conversations/<conversation_id>")
def memory_delete_conversation(conversation_id: str) -> Any:
    """Delete one prior conversation (messages + linked searches) for a persona."""
    persona_id = (request.args.get("persona_id") or "").strip() or None
    store = get_memory_store()
    deleted = store.delete_conversation(conversation_id, persona_id=persona_id)
    if not deleted:
        return jsonify(
            {"error": "conversation not found", "id": conversation_id}
        ), 404
    return jsonify({"deleted": True, "id": conversation_id}), 200


@app.delete("/api/memory/conversations")
def memory_delete_all_conversations() -> Any:
    """Delete all prior conversations for a persona."""
    persona_id = (request.args.get("persona_id") or "").strip()
    if not persona_id:
        return jsonify({"error": "persona_id is required"}), 400
    store = get_memory_store()
    store.ensure_persona(persona_id)
    deleted = store.delete_all_conversations(persona_id)
    return jsonify({"deleted": True, "persona_id": persona_id, "count": deleted}), 200


@app.post("/api/messages")
def messages() -> Any:
    """
    Intercept Microsoft Bot Framework message activities.

    Accepts both nested (`conversation.id`) and flat (`conversationId` /
    `activityId`) schemas used by emulator and the Streamlit validation UI.
    """
    activity = request.get_json(silent=True) or {}
    if not isinstance(activity, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400

    activity_type = activity.get("type", "message")
    if activity_type != "message":
        # Acknowledge non-message activities (conversationUpdate, etc.) without LLM work.
        return jsonify({"status": "ignored", "type": activity_type}), 200

    user_text = (activity.get("text") or "").strip()
    if not user_text:
        return jsonify({"error": "Activity text is required"}), 400

    conversation_id = _conversation_id(activity)
    persona_id, persona_name = _persona_from_activity(activity)
    channel_data = activity.get("channelData") or {}
    client_persists = False
    if isinstance(channel_data, dict):
        client_persists = bool(channel_data.get("clientPersistsMemory"))

    store = get_memory_store()
    store.ensure_persona(persona_id, persona_name)
    store.ensure_conversation(conversation_id, persona_id)

    logger.info(
        "Inbound activity activityId=%s conversationId=%s personaId=%s channelId=%s",
        _activity_id(activity),
        conversation_id,
        persona_id,
        activity.get("channelId"),
    )

    # History excludes the current turn (UI may already have persisted it).
    chat_history = _history_messages(conversation_id)
    if chat_history and isinstance(chat_history[-1], HumanMessage):
        if str(chat_history[-1].content).strip() == user_text:
            chat_history = chat_history[:-1]

    # Persist for non-UI clients; Streamlit sets clientPersistsMemory=true.
    if not client_persists:
        msgs = store.get_messages(conversation_id)
        last = msgs[-1] if msgs else None
        already_user = (
            last is not None
            and str(last.get("role")) == "user"
            and str(last.get("content") or "").strip() == user_text
        )
        if not already_user:
            store.append_message(
                conversation_id,
                "user",
                user_text,
                persona_id=persona_id,
            )

    try:
        answer = _submit(
            run_turn(
                user_text,
                chat_history=chat_history,
                persona_id=persona_id,
                conversation_id=conversation_id,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Agent turn failed")
        answer = f"Sorry — I hit an error while processing that: {exc}"

    if not client_persists:
        store.append_message(
            conversation_id,
            "assistant",
            str(answer),
            persona_id=persona_id,
            record_search=False,
        )
        store.update_latest_search_preview(persona_id, conversation_id, str(answer))

    reply = _build_reply(activity, answer)
    return jsonify(reply), 200


def main() -> None:
    host = get("COPILOT_HOST", "0.0.0.0")
    port = int(get("COPILOT_PORT", "3978"))
    # threaded=True lets Flask accept concurrent POSTs while agent work runs on _loop.
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
