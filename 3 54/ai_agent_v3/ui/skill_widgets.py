"""One checkbox per skill. The persistent store is the single source of truth.

The widget key contains the current value, so when the value changes anywhere (menu, Skills page,
chip) the checkbox is simply re-created with the right state – no widget-state syncing needed.
"""
import streamlit as st

from core import settings_store, skills


def skill_checkbox(skill: skills.Skill, where: str) -> None:
    enabled = skills.is_enabled(skill.id)
    tag = {"agent": " · agent", "chat": " · chat"}.get(skill.scope, "")
    warn = " ⚠️" if skill.warning else ""
    label = f"{skill.icon} **{skill.name}**{warn}  :gray[{skill.short}{tag}]"
    new = st.checkbox(label, value=enabled, key=f"{where}_{skill.id}_{int(enabled)}",
                      help=(skill.warning or skill.description))
    if new != enabled:
        skills.set_enabled(skill.id, new)
        st.rerun()


def force_web_checkbox(where: str) -> None:
    on = bool(settings_store.get("force_web", False))
    new = st.checkbox("🌐 **Vždy hľadať na webe**  :gray[pri každej správe]", value=on,
                      key=f"{where}_force_web_{int(on)}")
    if new != on:
        settings_store.put("force_web", new)
        st.rerun()
