"""
Cognitive Routing Agent — Flask ingress for Microsoft Bot Framework activities.

`/api/messages` accepts Bot Framework JSON payloads and runs the LangChain
agent on a dedicated asyncio loop in a background thread to avoid Flask
thread locking / nested-loop deadlocks.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import Flask, jsonify, request

from agent import run_turn
from config import get

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

    logger.info(
        "Inbound activity activityId=%s conversationId=%s channelId=%s",
        _activity_id(activity),
        _conversation_id(activity),
        activity.get("channelId"),
    )

    try:
        answer = _submit(run_turn(user_text))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Agent turn failed")
        answer = f"Sorry — I hit an error while processing that: {exc}"

    reply = _build_reply(activity, answer)
    # Bot Framework clients often expect 200/201 with the activity body or empty.
    # Returning the reply activity enables the Streamlit validation UI to display it.
    return jsonify(reply), 200


def main() -> None:
    host = get("COPILOT_HOST", "0.0.0.0")
    port = int(get("COPILOT_PORT", "3978"))
    # threaded=True lets Flask accept concurrent POSTs while agent work runs on _loop.
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
