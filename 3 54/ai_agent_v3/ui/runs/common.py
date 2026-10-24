"""Pieces shared by all run modes."""
from __future__ import annotations

import streamlit as st

from core import notify
from core.workspace import save_generated_code
from ui import state


def stop_button() -> None:
    # Clicking this (or any widget) interrupts the script run; state.recover_partial() keeps the text so far.
    st.button("⏹ Zastaviť", key="stop_generation", help="Preruší generovanie, uloží sa čo už vzniklo")


def new_partial(meta: dict, trace: list | None = None) -> dict:
    ss = st.session_state
    ss.partial = {"chat_id": ss.chat_id, "content": "", "thinking": "", "meta": dict(meta),
                  "trace": trace if trace is not None else []}
    return ss.partial


def finish(settings, content: str, *, thinking=None, trace=None, meta: dict, autosave: bool = True,
           no_file_hint: str = "") -> None:
    """Save the assistant message (+ auto-save code blocks if the write skill is on) and redraw."""
    saved = []
    if autosave and "fs_write" in settings.enabled and content:
        topic = next((m["content"] for m in reversed(st.session_state.messages) if m["role"] == "user"), "")
        saved = save_generated_code(content, topic)
    if no_file_hint and not saved:                # asked for a file, but nothing was saved -> tell how to get one
        content += no_file_hint
    if saved:
        meta["files"] = list(dict.fromkeys([*meta.get("files", []), *saved]))
    notify.task_done(meta.get("total_s"), ok=not meta.get("error"))
    st.session_state.partial = None
    state.add_message("assistant", content, thinking=thinking, trace=trace or [], meta=meta)
    st.rerun()                                    # redraw with action buttons + fresh sidebar
