"""
Lightweight Bot Framework stand-in for Validation UI testing.

Mirrors POST /api/messages without Azure / MCP / LangChain dependencies.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "val-mock-messages"})


@app.post("/api/messages")
def messages():
    activity = request.get_json(silent=True) or {}
    if activity.get("type", "message") != "message":
        return jsonify({"status": "ignored", "type": activity.get("type")}), 200

    text = (activity.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Activity text is required"}), 400

    conversation = activity.get("conversation") or {}
    conversation_id = (
        (conversation.get("id") if isinstance(conversation, dict) else None)
        or activity.get("conversationId")
        or "default"
    )
    reply_to = activity.get("id") or activity.get("activityId")

    return jsonify(
        {
            "type": "message",
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "channelId": activity.get("channelId") or "emulator",
            "from": activity.get("recipient") or {"id": "val-copilot", "name": "VAL CoPilot"},
            "recipient": activity.get("from") or {"id": "user", "name": "User"},
            "conversation": {"id": conversation_id},
            "replyToId": reply_to,
            "text": f"[mock] Echo: {text}",
            "serviceUrl": activity.get("serviceUrl") or "",
        }
    ), 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=3978, threaded=True, use_reloader=False)
