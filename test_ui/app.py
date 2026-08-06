"""
Validation Agent — Streamlit integration harness.

Mocks Microsoft Bot Framework message activities and posts them exclusively to
the Cognitive Routing Agent at http://localhost:3978/api/messages.
Never queries mcp_server or databases directly.

Persists persona conversations + prior searches via the shared memory store
(`data/persona_memory.sqlite`) so users can resume old chats and re-run searches.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
import streamlit as st

from config import get

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from memory.store import get_memory_store  # noqa: E402

DEFAULT_URL = "http://localhost:3978/api/messages"
DEFAULT_PERSONA_ID = "validation-user"
DEFAULT_PERSONA_NAME = "Validation User"


def _build_activity(
    text: str,
    conversation_id: str,
    *,
    persona_id: str,
    persona_name: str,
) -> dict:
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
        "from": {"id": persona_id, "name": persona_name, "role": "user"},
        "conversation": {"id": conversation_id, "conversationType": "personal"},
        "conversationId": conversation_id,
        "recipient": {"id": "val-copilot", "name": "VAL CoPilot", "role": "bot"},
        "text": text,
        "textFormat": "plain",
        "locale": "en-US",
        "serviceUrl": "http://localhost:3978",
        "channelData": {
            "personaId": persona_id,
            "personaName": persona_name,
        },
    }


def _post_message(
    url: str,
    text: str,
    conversation_id: str,
    *,
    persona_id: str,
    persona_name: str,
    timeout: float = 120.0,
) -> dict:
    payload = _build_activity(
        text,
        conversation_id,
        persona_id=persona_id,
        persona_name=persona_name,
    )
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


def _init_state() -> None:
    store = get_memory_store()
    if "persona_id" not in st.session_state:
        st.session_state.persona_id = DEFAULT_PERSONA_ID
    if "persona_name" not in st.session_state:
        st.session_state.persona_name = DEFAULT_PERSONA_NAME
    store.ensure_persona(st.session_state.persona_id, st.session_state.persona_name)

    if "conversation_id" not in st.session_state:
        st.session_state.conversation_id = str(uuid.uuid4())
        store.ensure_conversation(
            st.session_state.conversation_id,
            st.session_state.persona_id,
        )

    if "messages" not in st.session_state:
        st.session_state.messages = _load_messages(st.session_state.conversation_id)

    if "pending_prompt" not in st.session_state:
        st.session_state.pending_prompt = None


def _load_messages(conversation_id: str) -> list[dict]:
    store = get_memory_store()
    loaded = store.get_messages(conversation_id)
    return [
        {
            "role": item["role"],
            "content": item["content"],
            "meta": item.get("meta"),
        }
        for item in loaded
    ]


def _start_new_conversation() -> None:
    store = get_memory_store()
    st.session_state.conversation_id = str(uuid.uuid4())
    store.ensure_conversation(
        st.session_state.conversation_id,
        st.session_state.persona_id,
    )
    st.session_state.messages = []


def _switch_conversation(conversation_id: str) -> None:
    store = get_memory_store()
    store.ensure_conversation(conversation_id, st.session_state.persona_id)
    st.session_state.conversation_id = conversation_id
    st.session_state.messages = _load_messages(conversation_id)


def _persist_turn(role: str, content: str, meta: dict | None = None) -> None:
    store = get_memory_store()
    store.append_message(
        st.session_state.conversation_id,
        role,
        content,
        meta=meta,
        persona_id=st.session_state.persona_id,
    )
    if role == "assistant":
        store.update_latest_search_preview(
            st.session_state.persona_id,
            st.session_state.conversation_id,
            content,
        )


def _render_sidebar(messages_url: str) -> str:
    store = get_memory_store()
    st.header("Persona memory")
    persona_name = st.text_input(
        "Persona / user name",
        value=st.session_state.persona_name,
        help="Persistent identity used to store and recall conversations/searches.",
    )
    persona_id = st.text_input(
        "Persona ID",
        value=st.session_state.persona_id,
        help="Stable ID for this user/persona across sessions.",
    )
    if persona_id != st.session_state.persona_id or persona_name != st.session_state.persona_name:
        st.session_state.persona_id = persona_id.strip() or DEFAULT_PERSONA_ID
        st.session_state.persona_name = persona_name.strip() or DEFAULT_PERSONA_NAME
        store.ensure_persona(st.session_state.persona_id, st.session_state.persona_name)
        _start_new_conversation()
        st.rerun()

    st.caption(f"DB: `{store.db_path}`")
    st.divider()

    st.header("Target")
    messages_url = st.text_input(
        "Messages endpoint",
        value=messages_url,
        help="Must point at the Flask /api/messages route (default localhost:3978).",
    )
    st.text_input("conversationId", value=st.session_state.conversation_id, disabled=True)
    cols = st.columns(2)
    if cols[0].button("New conversation", use_container_width=True):
        _start_new_conversation()
        st.rerun()
    if cols[1].button("Refresh memory", use_container_width=True):
        st.session_state.messages = _load_messages(st.session_state.conversation_id)
        st.rerun()

    st.divider()
    st.subheader("Previous conversations")
    conversations = store.list_conversations(st.session_state.persona_id, limit=25)
    if not conversations:
        st.caption("No saved conversations yet.")
    for conv in conversations:
        title = conv.get("title") or "(untitled)"
        label = f"{title[:48]} · {conv.get('message_count', 0)} msgs"
        selected = conv["id"] == st.session_state.conversation_id
        if st.button(
            ("● " if selected else "○ ") + label,
            key=f"conv-{conv['id']}",
            use_container_width=True,
            disabled=selected,
        ):
            _switch_conversation(conv["id"])
            st.rerun()

    st.divider()
    st.subheader("Previous searches")
    searches = store.list_searches(st.session_state.persona_id, limit=25)
    if not searches:
        st.caption("No prior searches stored yet.")
    for item in searches:
        query = str(item.get("query") or "").strip()
        preview = str(item.get("result_preview") or "").strip()
        with st.expander(query[:72] or "(empty search)", expanded=False):
            if preview:
                st.caption(preview)
            st.caption(f"Saved: {item.get('created_at')}")
            b1, b2 = st.columns(2)
            if b1.button("Re-run", key=f"rerun-{item['id']}", use_container_width=True):
                st.session_state.pending_prompt = query
                st.rerun()
            if b2.button(
                "Open chat",
                key=f"open-{item['id']}",
                use_container_width=True,
                disabled=not item.get("conversation_id"),
            ):
                if item.get("conversation_id"):
                    _switch_conversation(str(item["conversation_id"]))
                    st.rerun()

    st.divider()
    st.markdown(
        "**Contract**\n\n"
        "- `channelId` = `emulator`\n"
        "- Includes `activityId` + `conversationId` + persona\n"
        "- Never calls `mcp_server/` directly\n"
        "- Memory persists under `data/persona_memory.sqlite`"
    )
    return messages_url


def main() -> None:
    st.set_page_config(page_title="VAL CoPilot Validation UI", layout="wide")
    _init_state()

    st.title("VAL CoPilot — Validation UI")
    st.caption(
        "Structural integration harness with persistent persona memory. "
        "Traffic is mocked as Bot Framework activities and sent only to the "
        "Cognitive Routing Agent."
    )

    with st.sidebar:
        messages_url = _render_sidebar(get("COPILOT_MESSAGES_URL", DEFAULT_URL))

    for item in st.session_state.messages:
        with st.chat_message(item["role"]):
            st.markdown(item["content"])
            if item.get("meta"):
                with st.expander("Bot Framework exchange"):
                    st.json(item["meta"])

    prompt = st.session_state.pending_prompt or st.chat_input("Send a validation message…")
    if st.session_state.pending_prompt:
        st.session_state.pending_prompt = None
    if not prompt:
        return

    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    _persist_turn("user", prompt)

    with st.chat_message("assistant"):
        with st.spinner("Calling Cognitive Routing Agent…"):
            try:
                result = _post_message(
                    messages_url,
                    prompt,
                    st.session_state.conversation_id,
                    persona_id=st.session_state.persona_id,
                    persona_name=st.session_state.persona_name,
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
                _persist_turn("assistant", reply_text, meta=result)
            except requests.RequestException as exc:
                err = f"Request failed: {exc}"
                st.error(err)
                st.session_state.messages.append({"role": "assistant", "content": err})
                _persist_turn("assistant", err)


if __name__ == "__main__":
    main()
