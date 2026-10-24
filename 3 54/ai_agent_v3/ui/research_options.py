"""Deep Research options (popover above the input while 🔬 is on). Saved in settings.json."""
import streamlit as st

from config import RESEARCH_DEFAULT_STEPS, RESEARCH_MAX_STEPS
from core import settings_store


def load() -> dict:
    steps = int(settings_store.get("research_steps", RESEARCH_DEFAULT_STEPS))
    return {"steps": max(2, min(RESEARCH_MAX_STEPS, steps)),
            "pages": bool(settings_store.get("research_pages", True)),
            "confirm": bool(settings_store.get("research_confirm", False))}


def summary() -> str:
    o = load()
    return " · ".join([f"{o['steps']} krokov", "číta stránky" if o["pages"] else "len výsledky hľadania"]
                      + (["plán na schválenie"] if o["confirm"] else []))


def _save() -> None:
    ss = st.session_state
    settings_store.put("research_steps", int(ss.ropt_steps))
    settings_store.put("research_pages", bool(ss.ropt_pages))
    settings_store.put("research_confirm", bool(ss.ropt_confirm))


def render() -> None:
    o = load()
    st.caption("Platí pre ďalšiu správu. Úroveň premýšľania nastavíš tlačidlami pod chatom "
               "(u gpt-oss Low / Medium / High). Ak je zapnutý aj 🤝 Klaster, výskum má prednosť.")
    st.number_input("Počet krokov výskumu", min_value=2, max_value=RESEARCH_MAX_STEPS, value=o["steps"], step=1,
                    key="ropt_steps", on_change=_save,
                    help="Viac krokov = dôkladnejšie, ale dlhšie (každý krok = hľadanie + čítanie stránok + poznámky).")
    st.checkbox("📄 Čítať celé stránky (nielen úryvky z hľadania)", value=o["pages"], key="ropt_pages", on_change=_save)
    st.checkbox("✋ Najprv ukázať plán a počkať na moje spustenie", value=o["confirm"], key="ropt_confirm",
                on_change=_save, help="Plán môžeš upraviť (jeden riadok = jeden krok) a až potom výskum spustiť.")
