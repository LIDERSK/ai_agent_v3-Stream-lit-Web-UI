"""Dispatcher: picks the run mode for the pending user message."""
import streamlit as st

from ui.runs import agent, chat, cluster, research


def run_generation(settings) -> None:
    ss = st.session_state
    ss.generate = False                       # clear first so an error can never loop
    msgs = ss.messages
    if not msgs or msgs[-1]["role"] != "user":
        return
    with st.chat_message("assistant"):
        if "research" in settings.enabled:                    # 🔬 Deep Research: normal AND agent chat
            research.run(settings, msgs, msgs[-1])
        elif ss.chat_mode == "agent":
            agent.run(settings, msgs, msgs[-1])
        elif "cluster" in settings.enabled:
            cluster.run(settings, msgs, msgs[-1])
        else:
            chat.run(settings, msgs, msgs[-1])
