"""Pick WHO does WHAT in the cluster: for every role a PC and then one of the models installed on that PC.

Shown in the chat (popover above the input, only while 🤝 Klaster is on) and on the Customize page,
so the team can be changed before every message. The choice is remembered (settings.json).
"""
import streamlit as st

from config import NODES
from core import models
from core.ollama_client import check_node


def _pc_label(name: str) -> str:
    online, _ = check_node(NODES[name].url)
    return f"{'🟢' if online else '🔴'} {name}"


def summary() -> str:
    team = models.cluster_team()
    return " · ".join(f"{icon} {models.resolve_role_model(pc, m) or '—'}" for icon, (pc, m)
                      in zip(("🧠", "💻", "🔍"), (team[r] for r in models.ROLES)))


def render(where: str) -> None:
    st.caption("Pre každú úlohu vyber počítač a model, ktorý na ňom pobeží. ⭐ = model, ktorý sa na túto úlohu hodí. "
               "Ak je počítač vypnutý, úlohu prevezme druhý.")
    names = list(NODES)
    team = models.cluster_team()
    for role in models.ROLES:
        pc, chosen = team[role]
        st.markdown(f"**{models.ROLE_LABEL[role]}**")
        c1, c2 = st.columns([1, 1.4])
        new_pc = c1.selectbox("Počítač", names, index=names.index(pc), key=f"{where}_{role}_pc",
                              format_func=_pc_label, label_visibility="collapsed")
        online, _ = check_node(NODES[new_pc].url)
        options = [models.AUTO] + (models.choices(new_pc) if online else [])

        def fmt(v, role=role, node=new_pc):
            if v == models.AUTO:
                return f"🔎 Automaticky · {models.get_model(node) or 'nič'}"
            star = "⭐ " if models.recommended(role, node, v) else ""
            gb = models.size_gb(node, v)
            return f"{star}{v} {models.badges(node, v)}".strip() + (f" · {gb} GB" if gb else "")

        cur = chosen if (new_pc == pc and chosen in options) else models.AUTO
        new_model = c2.selectbox("Model", options, index=options.index(cur), format_func=fmt,
                                 key=f"{where}_{role}_model_{new_pc}", label_visibility="collapsed",
                                 disabled=not online, help=None if online else "Počítač je nedostupný.")
        new_chosen = None if new_model == models.AUTO else new_model
        if (new_pc, new_chosen) != (pc, chosen):
            models.set_cluster_role(role, new_pc, new_chosen)
            st.rerun()
