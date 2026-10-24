"""Entry point – only wires the pieces together. Run with:  streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="Lokálny AI Agent", page_icon="🤖", layout="wide",
                   initial_sidebar_state="expanded")

from ui import sidebar, state, styles  # noqa: E402
from ui.views import chat, skills, workspace  # noqa: E402

PAGES = {"chat": chat.render, "workspace": workspace.render, "skills": skills.render}


def main() -> None:
    styles.inject_css()
    if st.session_state.get("shutting_down"):  # "⏻ Vypnúť všetko": models out, Ollama stopped, tab closed, app ends
        sidebar.shutdown_everything()
    state.init_state()
    state.recover_partial()                    # keep text of an interrupted generation
    sidebar.render_sidebar()                   # new chat (normal/agent), navigation, history
    PAGES.get(st.session_state.page, chat.render)()


main()
