"""Session state + chat lifecycle. The only place that mutates st.session_state.messages."""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from config import DEFAULT_NODE, DEFAULT_TEMPERATURE, DEFAULT_TIER, NODES, THINKING_TIERS
from core import chat_store, settings_store, skills


@dataclass
class Settings:
    """Everything the user can choose; passed to the runs."""
    mode: str                    # "chat" | "agent"
    node: str
    tier: str
    temperature: float
    force_web: bool
    enabled: frozenset           # enabled skill ids
    custom_instructions: str


# ----------------------------------------------------------------- preferences
def save_prefs() -> None:
    """on_change callback of the composer widgets -> remembered across pages and restarts."""
    ss = st.session_state
    if ss.get("node_choice") in NODES:
        settings_store.put("node", ss.node_choice)
    if ss.get("tier_choice") in THINKING_TIERS:      # (None = user deselected the pill; ignored)
        settings_store.put("tier", ss.tier_choice)
    if ss.get("temperature") is not None:
        settings_store.put("temperature", float(ss.temperature))


def current_settings() -> Settings:
    ss = st.session_state
    return Settings(mode=ss.chat_mode, node=ss.node_choice, tier=ss.tier_choice,
                    temperature=float(ss.temperature), force_web=bool(settings_store.get("force_web", False)),
                    enabled=frozenset(skills.enabled_ids()),
                    custom_instructions=settings_store.get("custom_instructions", ""))


def _reset_transient() -> None:
    ss = st.session_state
    ss.generate, ss.editing_id, ss.partial = False, None, None


def init_state() -> None:
    ss = st.session_state
    ss.setdefault("page", "chat")
    ss.setdefault("uploader_n", 0)
    ss.setdefault("_staged", [])
    # Widget state is dropped when a widget is not rendered (e.g. on another page) -> re-seed from the store.
    node = settings_store.get("node", DEFAULT_NODE)
    tier = settings_store.get("tier", DEFAULT_TIER)
    if ss.get("node_choice") not in NODES:
        ss["node_choice"] = node if node in NODES else DEFAULT_NODE
    if ss.get("tier_choice") not in THINKING_TIERS:
        ss["tier_choice"] = tier if tier in THINKING_TIERS else DEFAULT_TIER
    if ss.get("temperature") is None:
        ss["temperature"] = float(settings_store.get("temperature", DEFAULT_TEMPERATURE))
    if "chat_id" not in ss:
        chats = chat_store.list_chats()
        if chats:
            open_chat(chats[0]["id"])
        else:
            new_chat()
    for key, default in {"generate": False, "editing_id": None, "partial": None,
                         "script_output": None}.items():
        ss.setdefault(key, default)
    ss["page"] = ss.get("page", "chat")


# ----------------------------------------------------------------- chats
def new_chat(mode: str = "chat") -> None:
    ss = st.session_state
    ss.chat_id, ss.messages, ss.chat_mode, ss.page = chat_store.new_chat_id(), [], mode, "chat"
    _reset_transient()


def open_chat(chat_id: str) -> None:
    ss = st.session_state
    ss.messages, ss.chat_mode = chat_store.load_chat_full(chat_id)
    ss.chat_id, ss.page = chat_id, "chat"
    _reset_transient()


def delete_chat(chat_id: str) -> None:
    chat_store.delete_chat(chat_id)
    if chat_id == st.session_state.chat_id:
        remaining = chat_store.list_chats()
        open_chat(remaining[0]["id"]) if remaining else new_chat()


def clear_chat() -> None:
    chat_store.delete_chat(st.session_state.chat_id)
    st.session_state.messages = []
    _reset_transient()


def chat_title() -> str:
    first = next((m for m in st.session_state.messages if m["role"] == "user"), None)
    if not first:
        return "Nový chat"
    text = first["content"].strip()
    title = text.splitlines()[0] if text else ""
    if not title and first["images"]:
        title = "📷 Obrázok"
    return title[:40] or "Nový chat"


def persist() -> None:
    """Save the current chat. Called after EVERY change so nothing is ever lost."""
    ss = st.session_state
    if ss.messages:
        chat_store.save_chat(ss.chat_id, chat_title(), ss.messages, ss.chat_mode)


def add_message(role: str, content: str, **extra) -> dict:
    msg = chat_store.normalize({"role": role, "content": content, **extra})
    st.session_state.messages.append(msg)
    persist()
    return msg


def recover_partial() -> None:
    """If a generation was interrupted (Stop button / any click), keep what was produced."""
    ss = st.session_state
    p, ss.partial = ss.get("partial"), None
    if not p or p["chat_id"] != ss.chat_id:
        return
    trace = p.get("trace") or []
    if not (p["content"].strip() or p["thinking"].strip() or trace or p["meta"].get("research")):
        return
    add_message("assistant", p["content"].strip() or "_(zastavené)_", thinking=p["thinking"] or None,
                trace=trace, meta={**p["meta"], "stopped": True})
