"""
Validation Agent — Streamlit integration harness.

Mocks Microsoft Bot Framework message activities and posts them exclusively to
the Cognitive Routing Agent at http://localhost:3978/api/messages.
Never queries mcp_server or databases directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import requests
import streamlit as st

from config import get

DEFAULT_URL = "http://localhost:3978/api/messages"


def _build_activity(text: str, conversation_id: str) -> dict:
    """Exact Bot Framework-style message activity schema for the emulator channel."""
    activity_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    return {
        "type": "message",
        "id": activity_id,
        "activityId": activity_id,
        "timestamp": now,
        "localTimestamp": now,
        "channelId": "emulator",
        "from": {"id": "validation-user", "name": "Validation User", "role": "user"},
        "conversation": {"id": conversation_id, "conversationType": "personal"},
        "conversationId": conversation_id,
        "recipient": {"id": "val-copilot", "name": "VAL CoPilot", "role": "bot"},
        "text": text,
        "textFormat": "plain",
        "locale": "en-US",
        "serviceUrl": "http://localhost:3978",
    }


def _post_message(url: str, text: str, conversation_id: str, timeout: float = 120.0) -> dict:
    payload = _build_activity(text, conversation_id)
    response = requests.post(url, json=payload, timeout=timeout)
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}
    return {
        "status_code": response.status_code,
        "request": payload,
        "response": body,
    }


def main() -> None:
    st.set_page_config(page_title="VAL CoPilot Validation UI", layout="wide")

    st.title("VAL CoPilot — Validation UI")
    st.caption(
        "Structural integration harness. Traffic is mocked as Bot Framework activities "
        "and sent only to the Cognitive Routing Agent."
    )

    with st.sidebar:
        st.header("Target")
        messages_url = st.text_input(
            "Messages endpoint",
            value=get("COPILOT_MESSAGES_URL", DEFAULT_URL),
            help="Must point at the Flask /api/messages route (default localhost:3978).",
        )
        if "conversation_id" not in st.session_state:
            st.session_state.conversation_id = str(uuid.uuid4())
        st.text_input("conversationId", value=st.session_state.conversation_id, disabled=True)
        if st.button("New conversation"):
            st.session_state.conversation_id = str(uuid.uuid4())
            st.session_state.messages = []
            st.rerun()
        st.divider()
        st.markdown(
            "**Contract**\n\n"
            "- `channelId` = `emulator`\n"
            "- Includes `activityId` + `conversationId`\n"
            "- Never calls `mcp_server/` or databases"
        )

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for item in st.session_state.messages:
        with st.chat_message(item["role"]):
            st.markdown(item["content"])
            if item.get("meta"):
                with st.expander("Bot Framework exchange"):
                    st.json(item["meta"])

    prompt = st.chat_input("Send a validation message…")
    if not prompt:
        return

    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        with st.spinner("Calling Cognitive Routing Agent…"):
            try:
                result = _post_message(
                    messages_url,
                    prompt,
                    st.session_state.conversation_id,
                )
                body = result["response"]
                reply_text = (
                    body.get("text")
                    if isinstance(body, dict)
                    else None
                ) or f"(HTTP {result['status_code']}) {body}"
                st.markdown(reply_text)
                with st.expander("Bot Framework exchange"):
                    st.json(result)
                st.session_state.messages.append(
                    {"role": "assistant", "content": reply_text, "meta": result}
                )
            except requests.RequestException as exc:
                err = f"Request failed: {exc}"
                st.error(err)
                st.session_state.messages.append({"role": "assistant", "content": err})


if __name__ == "__main__":
    main()
