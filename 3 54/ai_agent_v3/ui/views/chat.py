"""The chat page: composer bar + input + conversation + generation."""
import streamlit as st

from ui import chat_view, composer, generation


def render() -> None:
    settings = composer.render_bar()       # ＋ menu, PC, thinking depth (pinned at the bottom)
    composer.handle_input(settings)        # chat input -> adds the user message
    chat_view.render_header(settings)
    chat_view.render_history()
    if st.session_state.generate:
        generation.run_generation(settings)
    chat_view.render_scroll_helpers()
